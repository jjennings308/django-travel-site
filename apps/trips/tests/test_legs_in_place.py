"""Phase A of docs/plans/trip-items-and-confirmations.md: a leg evolves in place (planned ->
scheduled), is placed on its day (a travel section, or the automatic block), and the trip page
shows it once in "Getting around" and once on its day."""
from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import AccountSettings
from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.logistics import rough_duration
from apps.trips.models import Day, Section, TransportLeg, Trip, TripGrant, TripRole

User = get_user_model()
UTC = dt_timezone.utc


class RoughDurationTests(SimpleTestCase):
    def test_parses_itinerary_wording(self):
        cases = {"~45 min": 45, "2.5 hrs": 150, "~1 hr 15 min": 75, "1:15": 75, "90m": 90, "~2 h": 120,
                 "1 day": 1440}
        for text, minutes in cases.items():
            with self.subTest(text=text):
                self.assertEqual(rough_duration(text), timedelta(minutes=minutes))
        for text in ("", "soon", "—"):
            self.assertIsNone(rough_duration(text))


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)
        self.butzbach = City.objects.create(name="Butzbach", slug="butzbach", country=de, latitude=50.43,
                                            longitude=8.67, approval_status=ApprovalStatus.APPROVED)
        self.frankfurt = City.objects.create(name="Frankfurt", slug="frankfurt", country=de, latitude=50.11,
                                             longitude=8.68, approval_status=ApprovalStatus.APPROVED)
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 19), end_date=date(2027, 9, 22),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day2 = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 20))
        self.day3 = Day.objects.create(trip=self.trip, day_number=3, date=date(2027, 9, 21))
        self.travel = Section.objects.create(day=self.day2, section_type=Section.Type.TRAVEL,
                                             title="Morning — train south", order=1, content={})

    def leg(self, **kw):
        values = {"trip": self.trip, "date": date(2027, 9, 20), "origin": "Butzbach", "destination": "Frankfurt Hbf",
                  "mode": "train"}
        values.update(kw)
        return TransportLeg.objects.create(**values)

    def page(self, user=None):
        self.client.force_login(user or self.editor)
        return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))


class StageAndPlacementTests(Fixture):
    def test_stage_is_derived(self):
        leg = self.leg()
        self.assertEqual(leg.stage, "planned")
        leg.departure_at = datetime(2027, 9, 20, 8, tzinfo=UTC)
        leg.arrival_at = datetime(2027, 9, 20, 9, tzinfo=UTC)
        leg.save()
        self.assertEqual(leg.stage, "scheduled")

    def test_section_must_be_a_travel_section_of_that_day(self):
        other = Section.objects.create(day=self.day3, section_type=Section.Type.TRAVEL, order=1, content={})
        leg = TransportLeg(trip=self.trip, date=date(2027, 9, 20), origin="A", destination="B", section=other)
        with self.assertRaises(ValidationError):
            leg.full_clean()
        leg.section = self.travel
        leg.full_clean()

    def test_moving_the_date_clears_the_placement(self):
        leg = self.leg(section=self.travel)
        self.assertEqual(leg.section, self.travel)
        leg.date = date(2027, 9, 21)
        leg.save()
        leg.refresh_from_db()
        self.assertIsNone(leg.section)  # falls back to day 3's automatic block

    def test_same_day_planned_legs_follow_order(self):
        second = self.leg(origin="Frankfurt Hbf", destination="Augsburg Hbf", order=2)
        first = self.leg(order=1)
        self.assertEqual(list(self.trip.transport.all()), [first, second])


class PageTests(Fixture):
    def test_leg_once_in_getting_around_and_once_on_its_day(self):
        placed = self.leg(section=self.travel, est_duration=timedelta(minutes=45), origin="PlacedFrom")
        auto = self.leg(date=date(2027, 9, 21), origin="AutoFrom", destination="Somewhere")
        html = self.page().content.decode()
        self.assertEqual(html.count('id="leg-%d"' % placed.pk), 2)
        self.assertEqual(html.count('id="leg-%d"' % auto.pk), 2)
        day2 = html[html.index('id="day-2"'):html.index('id="day-3"')]
        self.assertIn("Morning — train south", day2)
        self.assertIn("PlacedFrom", day2)
        self.assertIn("~45 min", day2)
        day3 = html[html.index('id="day-3"'):]
        self.assertIn("AutoFrom", day3)
        self.assertIn("Getting around", day3)

    def test_day_total(self):
        self.leg(est_duration=timedelta(minutes=45), section=self.travel)
        self.leg(origin="Frankfurt Hbf", destination="Augsburg Hbf", est_duration=timedelta(hours=2, minutes=30),
                 section=self.travel, order=2)
        self.assertContains(self.page(), "2 legs · ~3 h 15 min")

    def test_stray_leg_flagged_for_editors_only(self):
        self.leg(date=date(2027, 12, 1), origin="Lost", destination="Found")
        self.assertContains(self.page(), "isn't one of this trip's days")
        self.assertNotContains(self.page(self.viewer), "isn't one of this trip's days")

    def test_editors_see_edit_and_quick_add_viewers_dont(self):
        leg = self.leg(section=self.travel)
        edit = reverse("trips:leg_edit", args=[self.trip.pk, leg.pk])
        add = reverse("trips:leg_quick_add", args=[self.trip.pk, self.day2.pk])
        page = self.page()
        self.assertContains(page, edit)
        self.assertContains(page, add)
        page = self.page(self.viewer)
        self.assertNotContains(page, edit)
        self.assertNotContains(page, add)

    def test_scheduled_times_in_the_legs_zones_for_a_non_utc_reader(self):
        AccountSettings.objects.update_or_create(user=self.viewer, defaults={"timezone": "America/Los_Angeles"})
        self.leg(origin="Frankfurt", destination="Munich", origin_timezone="Europe/Berlin",
                 destination_timezone="Europe/Berlin", departure_at=datetime(2027, 9, 20, 7, 0, tzinfo=UTC),
                 arrival_at=datetime(2027, 9, 20, 10, 30, tzinfo=UTC))
        page = self.page(self.viewer)
        self.assertContains(page, "9:00")   # 07:00 UTC is 09:00 in Berlin (CEST)
        self.assertContains(page, "12:30")
        self.assertNotContains(page, "12:00 AM")  # not Los Angeles time


class EditingTests(Fixture):
    def test_quick_add_creates_a_planned_leg_on_the_day(self):
        self.client.force_login(self.editor)
        url = reverse("trips:leg_quick_add", args=[self.trip.pk, self.day2.pk])
        response = self.client.post(url, {"origin": "Butzbach", "destination": "Frankfurt Hbf", "mode": "train",
                                           "est_duration": "~45 min", "notes": "RE30", "section": self.travel.pk})
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk]) + "#day-2",
                             fetch_redirect_response=False)
        leg = TransportLeg.objects.get()
        self.assertEqual((leg.date, leg.section, leg.is_planned, leg.est_duration, leg.notes),
                         (date(2027, 9, 20), self.travel, True, timedelta(minutes=45), "RE30"))
        self.assertEqual((leg.origin_city, leg.destination_city), (self.butzbach, self.frankfurt))
        self.client.post(url, {"origin": "Frankfurt Hbf", "destination": "Augsburg", "mode": "train"})
        self.assertEqual(TransportLeg.objects.order_by("order").last().order, 2)

    def test_quick_add_refuses_another_days_section(self):
        other = Section.objects.create(day=self.day3, section_type=Section.Type.TRAVEL, order=1, content={})
        self.client.force_login(self.editor)
        response = self.client.post(reverse("trips:leg_quick_add", args=[self.trip.pk, self.day2.pk]),
                                    {"origin": "A", "destination": "B", "mode": "train", "section": other.pk})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(TransportLeg.objects.exists())

    def test_add_travel_section(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:day_add_travel", args=[self.trip.pk, self.day3.pk]))
        self.assertTrue(self.day3.sections.filter(section_type=Section.Type.TRAVEL, title="Getting around").exists())

    def test_edit_page_permissions_and_placement(self):
        leg = self.leg()
        url = reverse("trips:leg_edit", args=[self.trip.pk, leg.pk])
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.editor)
        page = self.client.get(url)
        self.assertEqual(list(page.context["form"].fields["section"].queryset), [self.travel])
        back = reverse("trips:trip_detail", args=[self.trip.pk]) + "#leg-%d" % leg.pk
        response = self.client.post(url, {
            "mode": "train", "date": "2027-09-20", "est_duration": "45 min", "origin": "Butzbach",
            "destination": "Frankfurt Hbf", "origin_timezone": "Europe/Berlin",
            "destination_timezone": "Europe/Berlin", "departure_local": "", "arrival_local": "",
            "currency": "EUR", "section": self.travel.pk, "order": 3, "next": back})
        self.assertRedirects(response, back, fetch_redirect_response=False)
        leg.refresh_from_db()
        self.assertEqual((leg.section, leg.order, leg.est_duration), (self.travel, 3, timedelta(minutes=45)))

    def test_next_must_be_on_this_site(self):
        leg = self.leg()
        self.client.force_login(self.editor)
        response = self.client.post(reverse("trips:leg_delete", args=[self.trip.pk, leg.pk]),
                                    {"next": "https://evil.example/"})
        self.assertEqual(response["Location"], reverse("trips:trip_detail", args=[self.trip.pk]) + "#day-2")
        self.assertFalse(TransportLeg.objects.exists())

    def test_delete_is_editors_only(self):
        leg = self.leg()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse("trips:leg_delete", args=[self.trip.pk, leg.pk])).status_code, 403)
        self.assertTrue(TransportLeg.objects.exists())

    def test_travel_section_editor(self):
        self.client.force_login(self.editor)
        url = reverse("trips:section_edit", args=[self.trip.pk, self.day2.pk, self.travel.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
