"""Planned transport legs (a day, no times yet) and turning a logistics table into legs."""
from datetime import date, datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.forms import TransportLegForm
from apps.trips.models import Day, Section, TransportLeg, Trip, TripGrant, TripRole

User = get_user_model()
UTC = dt_timezone.utc


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)
        self.city = {n: City.objects.create(name=n, slug=n.lower(), country=de, latitude=lat, longitude=lng,
                                            approval_status=ApprovalStatus.APPROVED)
                     for n, lat, lng in (("Butzbach", 50.43, 8.67), ("Frankfurt", 50.11, 8.68), ("Augsburg", 48.37, 10.9))}
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 18), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.trip.cities.set([self.city["Butzbach"], self.city["Augsburg"]])
        self.day = Day.objects.create(trip=self.trip, date=date(2027, 9, 20), day_number=3)


class PlannedLegTests(Fixture):
    def form(self, **over):
        data = {"mode": "train", "date": "2027-09-20", "origin": "Butzbach", "origin_city": self.city["Butzbach"].pk,
                "origin_timezone": "Europe/Berlin", "departure_local": "", "destination": "Augsburg Hbf",
                "destination_city": self.city["Augsburg"].pk, "destination_timezone": "Europe/Berlin",
                "arrival_local": "", "currency": "EUR"}
        data.update(over)
        return TransportLegForm(data, instance=TransportLeg(trip=self.trip))

    def test_saved_with_a_day_and_no_times(self):
        form = self.form()
        self.assertTrue(form.is_valid(), form.errors)
        leg = form.save()
        self.assertTrue(leg.is_planned)
        self.assertEqual((leg.date, leg.departure_at, leg.arrival_at), (date(2027, 9, 20), None, None))

    def test_needs_a_day_without_times_and_both_times_or_none(self):
        form = self.form(date="")
        self.assertFalse(form.is_valid())
        self.assertIn("date", form.errors)
        form = self.form(departure_local="2027-09-20 10:00")
        self.assertFalse(form.is_valid())
        self.assertIn("arrival_local", form.errors)

    def test_times_set_the_date_in_the_origin_zone(self):
        form = self.form(date="", origin_timezone="America/Denver", destination_timezone="America/Denver",
                         departure_local="2027-09-20 23:30", arrival_local="2027-09-21 01:00")
        self.assertTrue(form.is_valid(), form.errors)
        leg = form.save()
        self.assertEqual(leg.departure_at, datetime(2027, 9, 21, 5, 30, tzinfo=UTC))
        self.assertEqual(leg.date, date(2027, 9, 20))  # the local day, not the UTC one

    def test_the_pickers_value_is_wall_clock_in_the_ends_zone(self):
        """datetime-local sends 2027-09-20T23:30 with no zone; the zone selects still decide."""
        form = self.form(date="", origin_timezone="America/Denver", destination_timezone="America/New_York",
                         departure_local="2027-09-20T23:30", arrival_local="2027-09-21T05:00",
                         add_return="on", return_departure_local="2027-09-24T08:00",
                         return_arrival_local="2027-09-24T10:15")
        self.assertTrue(form.is_valid(), form.errors)
        leg = form.save()
        self.assertEqual((leg.departure_at, leg.arrival_at),
                         (datetime(2027, 9, 21, 5, 30, tzinfo=UTC), datetime(2027, 9, 21, 9, 0, tzinfo=UTC)))
        back = form.return_leg  # departs in New York (EDT), arrives in Denver (MDT)
        self.assertEqual((back.departure_at, back.arrival_at),
                         (datetime(2027, 9, 24, 12, 0, tzinfo=UTC), datetime(2027, 9, 24, 16, 15, tzinfo=UTC)))
        html = form["return_departure_local"].as_widget()
        self.assertIn('type="datetime-local"', html)

    def test_planned_round_trip_needs_a_return_day(self):
        form = self.form(add_return="on")
        self.assertFalse(form.is_valid())
        self.assertIn("return_date", form.errors)
        form = self.form(add_return="on", return_date="2027-09-22")
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual((form.return_leg.date, form.return_leg.origin, form.return_leg.is_planned),
                         (date(2027, 9, 22), "Augsburg Hbf", True))

    def test_shown_as_planned_on_the_page_and_the_map(self):
        leg = TransportLeg.objects.create(trip=self.trip, date=date(2027, 9, 20), mode="train", origin="Butzbach",
                                          destination="Augsburg Hbf", origin_city=self.city["Butzbach"],
                                          destination_city=self.city["Augsburg"], notes="~3.5 hrs")
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        # Its day's timeline row (U3: _leg_row.html, compact): the "Planned" badge and "planned" detail.
        self.assertContains(page, 'id="leg-%d"' % leg.pk, count=1)
        self.assertContains(page, "Planned")
        self.assertContains(page, '<span class="text-zinc-500">planned')
        data = self.client.get(reverse("trips:trip_map_data", args=[self.trip.pk])).json()
        line = [f for f in data["features"] if f["geometry"]["type"] == "LineString"][0]
        self.assertTrue(line["properties"]["planned"])
        self.assertIn("planned, no times yet", line["properties"]["subtitle"])
        self.assertTrue(leg.is_planned)


class SectionToLegsTests(Fixture):
    def setUp(self):
        super().setUp()
        self.section = Section.objects.create(
            day=self.day, section_type=Section.Type.LOGISTICS_TABLE, title="Getting to Augsburg", order=1,
            content={"columns": ["Transport Leg", "Train", "Time", "Notes"], "rows": [
                ["Butzbach → Frankfurt Hbf", "RE30", "~45 min", "Frequent"],
                ["Frankfurt Hbf → Augsburg Hbf", "ICE direct", "~2.5 hrs", "Book ahead"],
                ["Total journey", "—", "~3.5 hrs", "Mid-afternoon"]]})
        self.url = reverse("trips:section_to_legs", args=[self.trip.pk, self.day.pk, self.section.pk])

    def post_data(self, page, **over):
        formset = page.context["formset"]
        data = {f"legs-{k}": v for k, v in (("TOTAL_FORMS", formset.total_form_count()),
                                              ("INITIAL_FORMS", formset.initial_form_count()),
                                              ("MIN_NUM_FORMS", 0), ("MAX_NUM_FORMS", 1000))}
        for i, form in enumerate(formset.forms):
            for name in form.fields:
                value = form[name].value()
                if value is None or value is False:
                    continue
                data[form.add_prefix(name)] = "on" if value is True else str(value)
        data.update(over)
        return data

    def test_review_saves_nothing_and_confirm_makes_planned_legs(self):
        self.client.force_login(self.editor)
        page = self.client.get(self.url)
        self.assertEqual(len(page.context["rows"]), 2)
        self.assertFalse(TransportLeg.objects.exists())
        first = page.context["rows"][0][1]
        self.assertEqual((first["origin_city"], first["destination_city"]),
                         (self.city["Butzbach"], self.city["Frankfurt"]))  # Frankfurt from the catalogue
        self.client.post(self.url, self.post_data(page))
        legs = list(TransportLeg.objects.order_by("pk"))
        self.assertEqual([(l.origin, l.destination, l.mode, l.operator, l.is_planned, l.date) for l in legs], [
            ("Butzbach", "Frankfurt Hbf", "train", "RE30", True, date(2027, 9, 20)),
            ("Frankfurt Hbf", "Augsburg Hbf", "train", "ICE direct", True, date(2027, 9, 20))])
        self.assertEqual((legs[0].notes, legs[0].est_duration_str), ("Frequent", "~45 min"))
        self.assertEqual(legs[1].notes, "Book ahead · Mid-afternoon")  # the total row's note
        self.assertIn(self.city["Frankfurt"], self.trip.cities.all())
        self.section.refresh_from_db()
        # Phase C: the table became a travel section holding its legs; every row was converted.
        self.assertEqual(self.section.section_type, Section.Type.TRAVEL)
        self.assertNotIn("rows", self.section.content)
        self.assertEqual(list(self.section.legs.order_by("order")), legs)

    def test_existing_leg_is_linked_not_duplicated(self):
        existing = TransportLeg.objects.create(trip=self.trip, date=date(2027, 9, 20), origin="Butzbach",
                                               destination="Frankfurt Hbf")
        self.client.force_login(self.editor)
        page = self.client.get(self.url)
        self.assertEqual([p["action"] for _, p in page.context["rows"]], ["link", "create"])
        self.client.post(self.url, self.post_data(page))
        self.assertEqual(TransportLeg.objects.count(), 2)  # the existing one + Frankfurt → Augsburg
        existing.refresh_from_db()
        self.assertEqual((existing.section, existing.operator, existing.est_duration_str),
                         (self.section, "RE30", "~45 min"))  # placed, and gained what it lacked

    def test_existing_leg_found_by_cities_when_worded_differently(self):
        TransportLeg.objects.create(trip=self.trip, date=date(2027, 9, 20), origin="Butzbach Hof",
                                    destination="Frankfurt Hof")
        self.client.force_login(self.editor)
        rows = self.client.get(self.url).context["rows"]
        self.assertEqual([p["action"] for _, p in rows], ["link", "create"])

    def test_editors_only(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_link_on_the_section_page_not_the_view_page(self):
        self.client.force_login(self.editor)
        self.assertNotContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), self.url)
        self.assertContains(self.client.get(reverse("trips:section_edit",
                                                    args=[self.trip.pk, self.day.pk, self.section.pk])), self.url)
