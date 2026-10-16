"""Phase B of docs/plans/trip-items-and-confirmations.md: confirmations attached to the items
they confirm, the Quick reference generated from them, and the move of the old inline numbers."""
from datetime import date, datetime, timezone as dt_timezone
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.trips.models import Confirmation, Day, Lodging, Meal, Section, TransportLeg, Traveler, Trip, TripGrant, TripRole

User = get_user_model()
UTC = dt_timezone.utc


class MoveNumbersMigrationTests(TransactionTestCase):
    """trips 0023 on old-style data: numbers typed on legs and stays link to the trip's existing
    confirmation with that number, else become one confirmation per number."""

    BEFORE = [("trips", "0022_confirmation_links")]
    AFTER = [("trips", "0023_move_confirmation_numbers")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_links_to_existing_and_dedupes(self):
        apps = self.migrate(self.BEFORE)
        Trip = apps.get_model("trips", "Trip")
        Leg = apps.get_model("trips", "TransportLeg")
        Stay = apps.get_model("trips", "Lodging")
        Conf = apps.get_model("trips", "Confirmation")
        taos = Trip.objects.create(name="Taos", start_date=date(2026, 9, 12), end_date=date(2026, 9, 19))
        other = Trip.objects.create(name="Other", start_date=date(2026, 9, 12), end_date=date(2026, 9, 19))
        when = datetime(2026, 9, 12, 14, tzinfo=UTC)
        legs = [Leg.objects.create(trip=taos, origin=a, destination=b, operator="Delta", confirmation_number=n,
                                   departure_at=when, arrival_at=when, date=date(2026, 9, 12))
                for a, b, n in (("BWI", "ATL", "GCH7JS"), ("ATL", "ABQ", " gch7js "), ("ABQ", "SLC", "GCH7JS"))]
        chimayo = Stay.objects.create(trip=taos, name="Hotel Chimayo", confirmation_number="5305434791",
                                      check_in=date(2026, 9, 12), check_out=date(2026, 9, 13))
        angel = Stay.objects.create(trip=taos, name="Angel Fire Cabin", confirmation_number="Reservation-1216125",
                                    check_in=date(2026, 9, 13), check_out=date(2026, 9, 19))
        delta = Conf.objects.create(trip=taos, label="Flights (Delta, all 4 legs)", confirmation_number="GCH7JS")
        hotel = Conf.objects.create(trip=taos, label="Hotel Chimayo, Santa Fe", confirmation_number="5305434791")
        Conf.objects.create(trip=taos, label="Angel Fire", confirmation_number="EVRN0002048844001")
        Conf.objects.create(trip=taos, label="Travel Insurance", confirmation_number="EUSP2592862107")
        other_leg = Leg.objects.create(trip=other, origin="X", destination="Y", confirmation_number="GCH7JS",
                                       departure_at=when, arrival_at=when, date=date(2026, 9, 12))

        apps = self.migrate(self.AFTER)
        Conf = apps.get_model("trips", "Confirmation")
        delta = Conf.objects.get(pk=delta.pk)
        self.assertEqual(sorted(delta.legs.values_list("pk", flat=True)), sorted(l.pk for l in legs))
        self.assertEqual(list(Conf.objects.get(pk=hotel.pk).stays.values_list("pk", flat=True)), [chimayo.pk])
        made = Conf.objects.get(trip_id=taos.pk, confirmation_number="Reservation-1216125")
        self.assertEqual(list(made.stays.values_list("pk", flat=True)), [angel.pk])
        self.assertEqual(Conf.objects.filter(trip_id=taos.pk).count(), 5)  # 4 existing + Angel Fire's other number
        self.assertFalse(Conf.objects.get(confirmation_number="EUSP2592862107").legs.exists())  # loose stays loose
        # Another trip's same number is its own confirmation, never the Taos one.
        theirs = Conf.objects.get(trip_id=other.pk)
        self.assertEqual(list(theirs.legs.values_list("pk", flat=True)), [other_leg.pk])


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Taos", start_date=date(2026, 9, 12), end_date=date(2026, 9, 19),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2026, 9, 12))
        when = datetime(2026, 9, 12, 14, tzinfo=UTC)
        self.bwi = TransportLeg.objects.create(trip=self.trip, mode="plane", operator="Delta", origin="BWI",
                                               destination="ATL", departure_at=when, arrival_at=when)
        self.atl = TransportLeg.objects.create(trip=self.trip, mode="plane", operator="Delta", origin="ATL",
                                               destination="ABQ", departure_at=when, arrival_at=when, order=1)
        self.stay = Lodging.objects.create(trip=self.trip, name="Hotel Chimayo", check_in=date(2026, 9, 12),
                                           check_out=date(2026, 9, 13))
        self.meal = Meal.objects.create(day=self.day, name="Rancho de Chimayó", meal_type=Meal.MealType.DINNER)
        self.tour = Section.objects.create(day=self.day, section_type="phase", title="Georgia O'Keeffe Landscape Tour",
                                           content={"heading": "Georgia O'Keeffe Landscape Tour"})
        self.sara = Traveler.objects.create(name="Sara Test")
        self.trip.travelers.add(self.sara)
        self.other = Trip.objects.create(name="Other", start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
        self.other_leg = TransportLeg.objects.create(trip=self.other, origin="X", destination="Y", date=date(2026, 1, 1))


def linked(confirmation, model):
    """The items of one model a confirmation is linked to, in pk order."""
    return sorted((item for item in confirmation.covered_items() if isinstance(item, model)), key=lambda i: i.pk)


class AttachTests(Fixture):
    def test_attach_number_links_existing_case_insensitive(self):
        existing = Confirmation.objects.create(trip=self.trip, label="Flights", confirmation_number="GCH7JS")
        self.assertEqual(Confirmation.attach_number(self.trip, " gch7js ", self.bwi), existing)
        self.assertEqual(Confirmation.attach_number(self.trip, "GCH7JS", self.atl), existing)
        self.assertEqual(linked(existing, TransportLeg), [self.bwi, self.atl])
        made = Confirmation.attach_number(self.trip, "5305434791", self.stay, "Booking.com")
        self.assertEqual((made.provider, linked(made, Lodging)), ("Booking.com", [self.stay]))
        self.assertIsNone(Confirmation.attach_number(self.trip, "  ", self.stay))

    def test_links_only_within_the_trip_and_once_per_item(self):
        conf = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS")
        conf.link(self.bwi)
        conf.link(self.bwi)
        self.assertEqual(conf.links.count(), 1)
        with self.assertRaises(ValueError):
            conf.link(self.other_leg)

    def test_deleting_an_item_deletes_its_links_not_the_confirmation(self):
        conf = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS")
        conf.link(self.bwi)
        conf.link(self.meal)
        self.bwi.delete()
        self.assertEqual([link.item for link in conf.links.all()], [self.meal])

    def test_stage_becomes_booked(self):
        self.assertEqual(self.bwi.stage, "scheduled")
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.bwi)
        self.assertEqual(TransportLeg.objects.get(pk=self.bwi.pk).stage, "booked")


class ItemConfirmationsTests(Fixture):
    def url(self, kind, item):
        return reverse("trips:item_confirmations", args=[self.trip.pk, kind, item.pk])

    def test_add_by_number_links_an_existing_one_like_a_comment(self):
        self.client.force_login(self.editor)
        self.client.post(self.url("leg", self.bwi), {"action": "add", "confirmation_number": "GCH7JS",
                                                     "provider": "Delta"})
        self.client.post(self.url("leg", self.atl), {"action": "add", "confirmation_number": "gch7js"})
        conf = Confirmation.objects.get()
        self.assertEqual((conf.provider, linked(conf, TransportLeg)), ("Delta", [self.bwi, self.atl]))
        self.client.post(self.url("meal", self.meal), {"action": "attach", "confirmation": conf.pk})
        self.client.post(self.url("section", self.tour), {"action": "add", "confirmation_number": "378234488",
                                                           "provider": "Ghost Ranch"})
        self.assertEqual(Confirmation.objects.get(confirmation_number="378234488").kind, "activity")
        self.assertEqual(conf.description(), "BWI→ATL, ATL→ABQ, Rancho de Chimayó · Sat Sep 12")
        self.client.post(self.url("leg", self.bwi), {"action": "detach", "confirmation": conf.pk})
        self.assertEqual(linked(conf, TransportLeg), [self.atl])
        self.assertTrue(Confirmation.objects.filter(pk=conf.pk).exists())  # removing never deletes

    def test_stay_page_and_return_to(self):
        self.client.force_login(self.editor)
        page = self.client.get(self.url("stay", self.stay))
        self.assertContains(page, "Hotel Chimayo")
        back = reverse("trips:trip_edit", args=[self.trip.pk])
        response = self.client.post(self.url("stay", self.stay), {"action": "add", "confirmation_number": "5305434791",
                                                                   "return_to": back})
        self.assertRedirects(response, back, fetch_redirect_response=False)

    def test_another_trips_item_or_confirmation_is_refused(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("trips:item_confirmations",
                                                 args=[self.trip.pk, "leg", self.other_leg.pk])).status_code, 404)
        theirs = Confirmation.objects.create(trip=self.other, confirmation_number="ZZZ")
        self.assertEqual(self.client.post(self.url("leg", self.bwi), {"action": "attach",
                                                                      "confirmation": theirs.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("trips:item_confirmations",
                                                 args=[self.trip.pk, "trip", self.trip.pk])).status_code, 404)

    def test_permissions(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url("leg", self.bwi)).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url("leg", self.bwi)).status_code, 403)

    def test_leg_page_has_the_block(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:leg_edit", args=[self.trip.pk, self.bwi.pk]))
        self.assertContains(page, self.url("leg", self.bwi))


class ConfirmationPageTests(Fixture):
    def test_loose_confirmation_and_covers_list(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:confirmation_new", args=[self.trip.pk]), {
            "confirmation_number": "EUSP2592862107", "provider": "Allianz", "label": "Travel Insurance",
            "travelers": [self.sara.pk]})
        loose = Confirmation.objects.get()
        self.assertEqual((loose.kind, list(loose.travelers.all())), ("other", [self.sara]))
        loose.link(self.bwi)
        page = self.client.get(reverse("trips:confirmation_edit", args=[self.trip.pk, loose.pk]))
        self.assertContains(page, "BWI→ATL")
        self.assertContains(page, reverse("trips:item_confirmations", args=[self.trip.pk, "leg", self.bwi.pk]))

    def test_permissions(self):
        url = reverse("trips:confirmation_new", args=[self.trip.pk])
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_delete_keeps_the_items(self):
        conf = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS")
        conf.link(self.bwi)
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:confirmation_delete", args=[self.trip.pk, conf.pk]))
        self.assertFalse(Confirmation.objects.exists())
        self.assertTrue(TransportLeg.objects.filter(pk=self.bwi.pk).exists())


class QuickReferenceTests(Fixture):
    def test_grouped_and_ordered_loose_last_and_chips_on_every_item(self):
        flights = Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", provider="Delta",
                                              label="Flights (Delta, all 4 legs)")
        flights.link(self.bwi)
        flights.link(self.atl)
        flights.travelers.add(self.sara)
        Confirmation.objects.create(trip=self.trip, confirmation_number="5305434791").link(self.stay)
        Confirmation.objects.create(trip=self.trip, confirmation_number="378234488", provider="Ghost Ranch").link(self.tour)
        Confirmation.objects.create(trip=self.trip, confirmation_number="TABLE1").link(self.meal)
        Confirmation.objects.create(trip=self.trip, confirmation_number="EUSP2592862107", provider="Allianz",
                                    label="Travel Insurance")
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        titles = [title for title, _items in page.context["confirmation_groups"]]
        self.assertEqual(titles, ["Flights", "Stays", "Activities", "Meals", "Other"])
        html = page.content.decode()
        quick = html[html.index('id="reference"'):]
        self.assertEqual(quick.count("GCH7JS"), 1)  # once in Reference, its home
        self.assertIn("BWI→ATL, ATL→ABQ · Sat Sep 12", quick)
        self.assertIn("For Sara Test", quick)
        body = html[:html.index('id="reference"')]
        self.assertEqual(body.count("GCH7JS · Delta"), 2)  # a chip on each of its two legs, on their day
        self.assertIn(f'href="#confirmation-{flights.pk}"', body)  # chips link to their row
        self.assertIn("378234488 · Ghost Ranch", body)  # the day's plan section
        self.assertIn("TABLE1", body)  # the meal
        self.assertIn("Booked", html)


class ViewPageIsForReadingTests(Fixture):
    def test_no_add_forms_or_links_on_the_view_page(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        for marker in (reverse("trips:confirmation_new", args=[self.trip.pk]),
                       reverse("trips:leg_quick_add", args=[self.trip.pk, self.day.pk]),
                       reverse("trips:day_add_travel", args=[self.trip.pk, self.day.pk]),
                       "Add confirmation"):
            self.assertNotIn(marker, html)
        self.assertIn(reverse("trips:leg_edit", args=[self.trip.pk, self.bwi.pk]), html)  # Edit links stay

    def test_edit_trip_has_travel_by_day_and_bookings(self):
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:trip_edit", args=[self.trip.pk])).content.decode()
        self.assertIn(reverse("trips:leg_quick_add", args=[self.trip.pk, self.day.pk]), html)
        self.assertIn(reverse("trips:item_confirmations", args=[self.trip.pk, "stay", self.stay.pk]), html)
        self.assertIn(reverse("trips:item_confirmations", args=[self.trip.pk, "leg", self.bwi.pk]), html)
        self.assertIn(reverse("trips:confirmation_new", args=[self.trip.pk]), html)


class AuditTests(Fixture):
    def test_audit_catches_a_planted_number_and_passes_clean(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS").link(self.bwi)
        self.trip.enable_public()
        with self.assertRaises(SystemExit) as caught:
            call_command("audit_public_leak", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(caught.exception.code, 0)
        self.trip.destination = "Taos GCH7JS"  # the public title now carries the number
        self.trip.save()
        with self.assertRaises(SystemExit) as caught:
            call_command("audit_public_leak", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(caught.exception.code, 1)
