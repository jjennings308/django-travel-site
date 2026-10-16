"""Content clean-up review (docs/plans/trip-page-ux.md, U7): the pure detector (tidy.py) on
Europe-style text, applying ticked suggestions (tidying.py), the page and the command."""
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.trips import tidy, tidying
from apps.trips.models import (BookingTask, Contact, Day, ItemLink, Lodging, Meal, Section, TaskOption,
                               TidyDismissal, TransportLeg, Trip, TripActivity, TripGrant, TripInfo, TripRole)

User = get_user_model()


def plain_day(number, **parts):
    day = {"id": number, "number": number, "date": None, "sections": [], "legs": [], "stays": [], "meals": [],
           "activities": []}
    day.update(parts)
    return day


def section(pk, type_, title="", **content):
    base = {"id": pk, "type": type_, "title": title, "summary": "", "highlights": [], "paragraphs": [], "text": "",
            "columns": [], "rows": []}
    base.update(content)
    return base


class DetectorTests(SimpleTestCase):
    def run_on(self, days, **extra):
        snap = {"notes": "", "days": days, "trip_legs": [], "trip_stays": [], "tasks": [], "known_numbers": [],
                "contact_phones": []}
        snap.update(extra)
        return tidy.suggest(snap)

    def test_lines_repeating_legs_stays_and_meals(self):
        day = plain_day(4, legs=[{"id": 1, "origin": "Butzbach Hof", "destination": "Frankfurt Hof"}],
                        stays=[{"id": 2, "name": "Hotel Hessischer Hof"}],
                        meals=[{"id": 3, "name": "Lebkuchen Schmidt", "notes": ""},
                               {"id": 4, "name": "Borough Market", "notes": ""}],
                        sections=[section(10, "phase", "Morning", summary="Check out Hotel Hessischer Hof after breakfast",
                                          highlights=["Train Butzbach → Frankfurt Hbf (~45 min on RE30)",
                                                      "Lebkuchen Schmidt — Nuremberg gingerbread, pick up tins",
                                                      "Thames walk: Borough Market → Tate Modern → Tower Bridge",
                                                      "A quiet afternoon"])])
        found = {s.before: s for s in self.run_on([day]) if s.kind == "repeats_item"}
        self.assertEqual(found["Check out Hotel Hessischer Hof after breakfast"].confidence, "high")
        self.assertEqual(found["Train Butzbach → Frankfurt Hbf (~45 min on RE30)"].change["item"], {"kind": "leg", "id": 1})
        lebkuchen = found["Lebkuchen Schmidt — Nuremberg gingerbread, pick up tins"]
        self.assertEqual((lebkuchen.confidence, lebkuchen.change["extra"]),
                         ("high", "Nuremberg gingerbread, pick up tins"))
        self.assertEqual(found["Thames walk: Borough Market → Tate Modern → Tower Bridge"].confidence, "low")
        self.assertNotIn("A quiet afternoon", found)

    def test_callout_repeating_a_task(self):
        day = plain_day(4, sections=[
            section(20, "callout", "📅 Book", text="ICE Frankfurt → Augsburg: book seat reservations for 6 people"),
            section(21, "callout", "💡 Tip", text="Keep the Augsburg afternoon genuinely easy")])
        tasks = [{"id": 7, "title": "ICE train seats Frankfurt→Augsburg (6 people)",
                  "item": {"kind": "leg", "id": 1, "label": "Frankfurt Hbf → Augsburg Hbf"}}]
        found = [s for s in self.run_on([day], tasks=tasks) if s.kind == "callout_task"]
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].confidence, [a for a, _ in found[0].actions]), ("high", ["delete", "to_info"]))

    def test_phone_numbers_become_contacts_on_the_named_meal(self):
        day = plain_day(2, meals=[{"id": 3, "name": "Ristorante Da Franco", "notes": "Call ahead: 06033 65147"}],
                        sections=[section(30, "free_text", "Evening", paragraphs=["Prices €38 and 2027–2028 times 9–11"])])
        found = [s for s in self.run_on([day], known_numbers=["5305434791"]) if s.kind == "phone"]
        self.assertEqual(len(found), 1)  # no price, year range or time mistaken for a phone
        self.assertEqual((found[0].change["number"], found[0].change["link"]), ("06033 65147", {"kind": "meal", "id": 3}))
        self.assertEqual(found[0].after, "Call ahead")

    def test_trip_notes_repeats_options_and_contact_blocks(self):
        notes = ("Hotels: Hotel Hessischer Hof, Butzbach (2 nights)\n\nAugsburg options:\n1. Hotel Augusta, Ludwigstr. 2\n"
                 "2. Steigenberger Drei Mohren\n3. Airbnb Altstadt\n\nTaxi Augsburg eG\nLocal taxi dispatch\n"
                 "Phone: +49 821 35025")
        found = {s.kind: s for s in self.run_on([], notes=notes, trip_stays=[{"id": 2, "name": "Hotel Hessischer Hof"}])}
        self.assertEqual(found["notes_repeat"].before, "Hotels: Hotel Hessischer Hof, Butzbach (2 nights)")
        self.assertEqual((found["notes_options"].change["title"], len(found["notes_options"].change["options"])),
                         ("Augsburg options", 3))
        phone = found["phone"]
        self.assertEqual((phone.change["name"], phone.change["notes"]), ("Taxi Augsburg eG", "Local taxi dispatch"))

    def test_table_describing_an_activity_and_day_slips(self):
        day = plain_day(7, activities=[{"id": 5, "title": "Nightwatchman tour"}], sections=[
            section(40, "logistics_table", "Nightwatchman Tour", columns=["When", "Where"], rows=[["8pm", "Marktplatz"]]),
            section(41, "callout", "💡 Tip", text="Day 3 is a travel day by design.")])
        kinds = {s.kind: s for s in self.run_on([day])}
        self.assertEqual(kinds["table_activity"].change["activity"], 5)
        self.assertTrue(kinds["day_slip"].flag_only)

    def test_dismissed_keys_are_left_out(self):
        day = plain_day(1, sections=[section(41, "callout", "Tip", text="Day 3 is a travel day.")])
        key = self.run_on([day])[0].key
        snap = {"notes": "", "days": [day]}
        self.assertEqual(tidy.suggest(snap, dismissed={key}), [])


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 19), end_date=date(2027, 9, 21),
                                        created_by=self.editor, notes="Taxi Augsburg eG\nLocal dispatch\nPhone: +49 821 35025")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=4, date=date(2027, 9, 20))
        self.leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="Frankfurt Hbf",
                                               destination="Augsburg Hbf", date=self.day.date)
        Lodging.objects.create(trip=self.trip, name="Hotel Hessischer Hof", check_in=date(2027, 9, 18),
                               check_out=self.day.date)
        self.phase = Section.objects.create(day=self.day, section_type="phase", title="Morning", content={
            "summary": "Check out Hotel Hessischer Hof after breakfast",
            "highlights": ["ICE Frankfurt Hbf → Augsburg (~2.5 hrs) — book 6 seats together", "Coffee first"]})
        self.callout = Section.objects.create(day=self.day, section_type="callout", title="📅 Book", order=1, content={
            "tone": "info", "text": "ICE Frankfurt → Augsburg: book seat reservations for 6 people together"})
        self.task = BookingTask.objects.create(trip=self.trip, title="ICE train seats Frankfurt→Augsburg (6 people)",
                                               leg=self.leg)
        self.url = reverse("trips:trip_tidy", args=[self.trip.pk])

    def suggestions(self):
        return tidying.suggestions(self.trip)


class ApplyTests(Fixture):
    def test_dry_run_saves_nothing_and_apply_changes_only_whats_ticked(self):
        found = self.suggestions()
        self.assertTrue(found)
        before = (Section.objects.count(), Contact.objects.count(), self.trip.notes)
        self.assertEqual((Section.objects.count(), Contact.objects.count(), self.trip.notes), before)
        ice = next(s for s in found if s.kind == "repeats_item" and s.before.startswith("ICE"))
        callout = next(s for s in found if s.kind == "callout_task")
        phone = next(s for s in found if s.kind == "phone")
        applied, skipped = tidying.apply(self.trip, found, {ice.key: "remove_keep", callout.key: "to_info",
                                                            phone.key: "contact"})
        self.assertEqual((len(applied), skipped), (3, []))
        self.phase.refresh_from_db()
        self.assertEqual(self.phase.content["highlights"], ["Coffee first"])
        self.assertEqual(self.phase.content["summary"], "Check out Hotel Hessischer Hof after breakfast")  # not ticked
        self.leg.refresh_from_db()
        self.assertIn("book 6 seats together", self.leg.notes)
        self.assertFalse(Section.objects.filter(pk=self.callout.pk).exists())
        info = TripInfo.objects.get()
        self.assertEqual(ItemLink.objects.get(source_id=info.pk).target, self.leg)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.notes, "")
        self.assertEqual(Contact.objects.get().name, "Taxi Augsburg eG")
        # A second run doesn't offer what was applied.
        keys = {s.key for s in self.suggestions()}
        self.assertFalse({ice.key, callout.key, phone.key} & keys)

    def test_atomic_a_failure_rolls_everything_back(self):
        found = self.suggestions()
        chosen = {s.key: s.actions[0][0] for s in found if s.actions}
        with mock.patch("apps.trips.tidying.Contact.objects.create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                tidying.apply(self.trip, found, chosen)
        self.phase.refresh_from_db()
        self.assertEqual(len(self.phase.content["highlights"]), 2)
        self.assertTrue(Section.objects.filter(pk=self.callout.pk).exists())

    def test_stale_suggestion_is_skipped(self):
        found = self.suggestions()
        ice = next(s for s in found if s.kind == "repeats_item" and s.before.startswith("ICE"))
        self.phase.content = {**self.phase.content, "highlights": ["Changed by hand", "Coffee first"]}
        self.phase.save()
        applied, skipped = tidying.apply(self.trip, found, {ice.key: "remove"})
        self.assertEqual((applied, len(skipped)), ([], 1))

    def test_notes_options_become_a_decision(self):
        self.trip.notes = "Augsburg options:\n1. Hotel Augusta\n2. Drei Mohren"
        self.trip.save()
        found = self.suggestions()
        options = next(s for s in found if s.kind == "notes_options")
        tidying.apply(self.trip, found, {options.key: "decision"})
        task = BookingTask.objects.get(kind="decide")
        self.assertEqual([o.title for o in task.options.all()], ["Hotel Augusta", "Drei Mohren"])


class PageTests(Fixture):
    def test_review_dismiss_and_apply(self):
        self.client.force_login(self.editor)
        page = self.client.get(self.url)
        self.assertContains(page, "Check out Hotel Hessischer Hof after breakfast")
        found = self.suggestions()
        summary = next(s for s in found if s.before.startswith("Check out"))
        self.client.post(self.url, {"dismiss": summary.key})
        self.assertTrue(TidyDismissal.objects.filter(key=summary.key).exists())
        self.assertNotContains(self.client.get(self.url), "Check out Hotel Hessischer Hof after breakfast")
        ice = next(s for s in found if s.before.startswith("ICE"))
        self.client.post(self.url, {f"pick-{ice.key}": "on", f"act-{ice.key}": "remove",
                                    f"act-{summary.key}": "remove"})  # an unticked action is ignored
        self.phase.refresh_from_db()
        self.assertEqual(self.phase.content["highlights"], ["Coffee first"])
        self.assertEqual(self.phase.content["summary"], "Check out Hotel Hessischer Hof after breakfast")

    def test_permissions_and_trip_page_link(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        detail = reverse("trips:trip_detail", args=[self.trip.pk])
        self.assertNotContains(self.client.get(detail), self.url)
        self.client.force_login(self.editor)
        self.assertContains(self.client.get(detail), self.url)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url).status_code, 404)


class CommandTests(Fixture):
    def cmd(self, *args):
        out = StringIO()
        call_command("tidy_trip", "--trip", str(self.trip.pk), *args, stdout=out)
        return out.getvalue()

    def test_dry_run_then_apply_exact_matches_only_then_nothing(self):
        self.assertIn("Dry run", self.cmd())
        self.assertEqual(Section.objects.count(), 2)
        self.cmd("--apply")
        self.phase.refresh_from_db()
        self.assertEqual(self.phase.content["highlights"], ["Coffee first"])  # exact leg match, removed
        self.assertEqual(self.phase.content["summary"], "")  # exact stay match, removed
        self.assertFalse(Section.objects.filter(pk=self.callout.pk).exists())  # "📅 Book" callout, deleted
        self.assertFalse(Contact.objects.exists())  # phones are never applied by the command
        self.trip.refresh_from_db()
        self.assertIn("+49 821 35025", self.trip.notes)
        out = self.cmd("--apply")
        self.assertIn("Applied 0", out)  # idempotent: only the review-page ones remain
