"""Phase C of docs/plans/trip-items-and-confirmations.md: a trip's logistics tables turned
into legs in one review (apps/trips/travel_tables.py), the trip page's banner, and
manage.py convert_travel_tables."""
from datetime import date, datetime, timezone as dt_timezone
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import Day, Section, TransportLeg, Trip, TripGrant, TripRole

User = get_user_model()
UTC = dt_timezone.utc

BAYERN = {"columns": ["Detail", "Info"], "rows": [
    ["Departure", "Augsburg Hbf → München Hbf, mid-morning (~10–10:30am). No early alarm."],
    ["Train", "Regional Express — ~35 min. Bayern Ticket valid"],
    ["Bayern Ticket (6 people)", "Buy 2: 5-person (~€38) + 1-person (~€22)"],
    ["München Hbf → Theresienwiese", "U4 or U5 subway — 2 stops, ~5 min."]]}
TO_MUC = {"columns": ["Leg", "Mode", "Time", "Notes"], "rows": [
    ["Augsburg Hbf → München Hbf", "Regional Express", "~35 min", "Final train"],
    ["München Hbf → Munich Airport (MUC)", "S-Bahn S8", "~40 min", "Every 10 min"],
    ["Total Augsburg → MUC", "—", "~1 hr 15 min", "Allow 2.5 hrs at MUC"]]}
SCHEDULE = {"columns": ["Time", "Stop", "Details"], "rows": [
    ["~10:15 AM", "Depart Santa Fe", "Via Hwy 503 → Hwy 76 (High Road)"],
    ["~3:00 PM", "Continue to Angel Fire", "Via Taos, then east ~30–40 min"]]}


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 20), end_date=date(2027, 9, 25),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day21 = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 21))
        self.day22 = Day.objects.create(trip=self.trip, day_number=3, date=date(2027, 9, 22))
        self.day25 = Day.objects.create(trip=self.trip, day_number=6, date=date(2027, 9, 25))
        self.bayern = Section.objects.create(day=self.day21, section_type="logistics_table", title="Bayern Ticket",
                                             content=BAYERN)
        self.schedule = Section.objects.create(day=self.day22, section_type="logistics_table", title="Day plan",
                                               content=SCHEDULE)
        self.muc = Section.objects.create(day=self.day25, section_type="logistics_table", title="To MUC",
                                          content=TO_MUC)
        # Already a leg on the 25th, typed differently and booked with times.
        when = datetime(2027, 9, 25, 8, tzinfo=UTC)
        self.booked = TransportLeg.objects.create(trip=self.trip, mode="train", origin="Augsburg Hbf",
                                                  destination="München Hbf", departure_at=when, arrival_at=when,
                                                  origin_timezone="UTC", destination_timezone="UTC")
        self.url = reverse("trips:trip_travel_review", args=[self.trip.pk])

    def post_data(self, page, **over):
        formset = page.context["formset"]
        data = {f"legs-{k}": v for k, v in (("TOTAL_FORMS", formset.total_form_count()),
                                              ("INITIAL_FORMS", formset.initial_form_count()),
                                              ("MIN_NUM_FORMS", 0), ("MAX_NUM_FORMS", 1000))}
        for form in formset.forms:
            for name in form.fields:
                value = form[name].value()
                if value is None or value is False:
                    continue
                data[form.add_prefix(name)] = "on" if value is True else str(value)
        data.update(over)
        return data


class TripWideReviewTests(Fixture):
    def test_review_then_convert_the_whole_trip(self):
        self.client.force_login(self.editor)
        page = self.client.get(self.url)
        self.assertEqual([g[0].section for g in page.context["groups"]], [self.bayern, self.schedule, self.muc])
        actions = [(p["origin"], p["action"], p["include"]) for _f, p in page.context["rows"]]
        self.assertEqual(actions, [
            ("Augsburg Hbf", "create", True), ("München Hbf", "create", True),
            ("Via Hwy 503", "create", False), ("Continue", "create", False),  # possible rows: unticked
            ("Augsburg Hbf", "link", True), ("München Hbf", "create", True)])
        self.assertEqual(TransportLeg.objects.count(), 1)  # the review saved nothing

        self.client.post(self.url, self.post_data(page))
        self.assertEqual(TransportLeg.objects.count(), 4)  # 3 made + the booked one, not doubled
        self.bayern.refresh_from_db()
        self.assertEqual(self.bayern.section_type, Section.Type.TRAVEL)
        self.assertEqual([r[0] for r in self.bayern.content["rows"]], ["Train", "Bayern Ticket (6 people)"])
        self.assertEqual(self.bayern.legs.count(), 2)
        self.schedule.refresh_from_db()
        self.assertEqual((self.schedule.section_type, self.schedule.content), ("logistics_table", SCHEDULE))
        self.muc.refresh_from_db()
        self.assertNotIn("rows", self.muc.content)  # both hops and the total gone
        self.booked.refresh_from_db()
        self.assertEqual((self.booked.section, self.booked.operator, self.booked.est_duration_str),
                         (self.muc, "Regional Express", "~35 min"))
        airport = TransportLeg.objects.get(destination="Munich Airport (MUC)")
        self.assertEqual((airport.section, airport.est_duration_str, airport.notes),
                         (self.muc, "~40 min", "Every 10 min · Allow 2.5 hrs at MUC"))
        # Nothing left to convert: the banner goes and the review is empty of arrow rows.
        page = self.client.get(self.url)
        self.assertFalse(any(p["include"] for _f, p in page.context["rows"]))

    def test_another_trips_section_is_ignored(self):
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        theirs = Section.objects.create(day=Day.objects.create(trip=other, day_number=1, date=date(2027, 1, 1)),
                                        section_type="logistics_table", content=TO_MUC)
        self.client.force_login(self.editor)
        page = self.client.get(self.url)
        data = self.post_data(page)
        for key in [k for k in data if k.endswith("-section")]:
            data[key] = str(theirs.pk)
        self.client.post(self.url, data)
        theirs.refresh_from_db()
        self.assertEqual(theirs.section_type, "logistics_table")
        self.assertEqual(TransportLeg.objects.count(), 1)

    def test_permissions(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_link_on_edit_trip_while_arrow_rows_remain(self):
        edit = reverse("trips:trip_edit", args=[self.trip.pk])
        self.client.force_login(self.editor)
        self.assertNotContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), self.url)
        self.assertContains(self.client.get(edit), self.url)
        Section.objects.filter(pk__in=[self.bayern.pk, self.muc.pk]).update(section_type="travel")
        self.assertNotContains(self.client.get(edit), self.url)  # only "possible" rows left


class CommandTests(Fixture):
    def run_command(self, *args):
        out = StringIO()
        call_command("convert_travel_tables", "--trip", str(self.trip.pk), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_saves_nothing_then_apply_then_nothing_to_do(self):
        out = self.run_command()
        self.assertIn("link    Augsburg Hbf → München Hbf = existing leg", out)
        self.assertIn("skip    Via Hwy 503", out)
        self.assertIn("no city for", out)
        self.assertIn("Dry run", out)
        self.assertEqual(TransportLeg.objects.count(), 1)
        self.assertEqual(Section.objects.filter(section_type="travel").count(), 0)
        self.assertIn("Made 3 planned legs, linked 1", self.run_command("--apply"))
        self.assertEqual(Section.objects.filter(section_type="travel").count(), 2)
        self.assertIn("Nothing to do.", self.run_command("--apply"))
        self.assertEqual(TransportLeg.objects.count(), 4)
