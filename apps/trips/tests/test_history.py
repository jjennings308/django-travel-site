"""Change history and undo (site roadmap R8)."""
import io
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.current import acting_as
from apps.trips import changes
from apps.trips.tests.helpers import make_task
from apps.trips.models import (
    BookingTask, Confirmation, ConfirmationLink, Contact, Day, ItemLink, Lodging, Meal, Section, TransportLeg,
    Traveler, Trip, TripActivity, TripChange, TripGrant, TripRole,
)

User = get_user_model()


class HistoryFixture(TestCase):
    def setUp(self):
        self.ed = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd", first_name="Ed")
        self.vi = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.co = User.objects.create_user("co", "co@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.ed)
        for user, role in ((self.ed, TripRole.EDITOR), (self.vi, TripRole.VIEWER), (self.co, TripRole.COMMENTOR)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 19))
        self.day2 = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 20))
        with acting_as(self.ed):
            self.leg = TransportLeg.objects.create(
                trip=self.trip, mode="train", operator="DB", origin="Frankfurt Hbf", destination="Augsburg Hbf",
                date=date(2027, 9, 19), departure_at=datetime(2027, 9, 19, 8, 0, tzinfo=dt_timezone.utc),
                arrival_at=datetime(2027, 9, 19, 11, 0, tzinfo=dt_timezone.utc),
                origin_timezone="Europe/Berlin", destination_timezone="Europe/Berlin")
        self.url = reverse("trips:trip_history", args=[self.trip.pk])

    def move_leg(self, hour=8, minute=30, user=None):
        with acting_as(user or self.ed):
            self.leg.departure_at = datetime(2027, 9, 19, hour, minute, tzinfo=dt_timezone.utc)
            self.leg.save()
        return TripChange.objects.latest("id")

    def undo(self, change, user=None):
        self.client.force_login(user or self.ed)
        return self.client.post(reverse("trips:change_undo", args=[self.trip.pk, change.pk]), follow=True)


class PageTests(HistoryFixture):
    def test_viewers_see_it_newest_first_with_links(self):
        self.move_leg()
        self.client.force_login(self.vi)
        html = self.client.get(self.url).content.decode()
        changed, added = html.index("Changed Frankfurt Hbf"), html.index("Added Frankfurt Hbf")
        self.assertLess(changed, added)
        self.assertIn(f"#leg-{self.leg.pk}", html)
        self.assertIn("Day 1", html)
        self.assertNotIn("data-undo", html)  # viewers can't undo

    def test_filters(self):
        self.move_leg()
        Meal.objects.create(day=self.day2, name="Bräustüberl", meal_type="dinner")  # no actor: a script
        self.client.force_login(self.vi)
        by_day = self.client.get(self.url, {"day": self.day2.pk}).content.decode()
        self.assertIn("Bräustüberl", by_day)
        self.assertNotIn("Frankfurt", by_day)
        by_person = self.client.get(self.url, {"person": self.ed.pk}).content.decode()
        self.assertIn("Frankfurt", by_person)
        self.assertNotIn("Bräustüberl", by_person)
        scripts = self.client.get(self.url, {"person": "none"}).content.decode()
        self.assertIn("Bräustüberl", scripts)
        by_kind = self.client.get(self.url, {"kind": "changed"}).content.decode()
        self.assertIn("Changed Frankfurt", by_kind)
        self.assertNotIn("Added Frankfurt", by_kind)

    def test_no_grant_is_a_404_and_trip_page_links_here(self):
        stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.vi)
        self.assertContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), self.url)


class UndoTests(HistoryFixture):
    def test_undo_puts_the_fields_back_and_is_recorded(self):
        change = self.move_leg()
        self.client.force_login(self.ed)
        self.assertContains(self.client.get(self.url), "data-undo")
        self.undo(change)
        self.leg.refresh_from_db()
        self.assertEqual(self.leg.departure_at, datetime(2027, 9, 19, 8, 0, tzinfo=dt_timezone.utc))
        latest = TripChange.objects.latest("id")
        self.assertIn("departs 10:30 AM CEST → 10:00 AM CEST", latest.summary)
        self.assertEqual(latest.actor, self.ed)

    def test_only_the_newest_change_and_not_after_an_edit(self):
        first = self.move_leg(8, 30)
        self.move_leg(9, 0)
        response = self.undo(first)
        self.assertContains(response, "changed again since")
        self.leg.refresh_from_db()
        self.assertEqual(self.leg.departure_at.hour, 9)
        # Edited behind the history's back (a queryset update records nothing).
        newest = TripChange.objects.latest("id")
        TransportLeg.objects.filter(pk=self.leg.pk).update(departure_at=datetime(2027, 9, 19, 12, 0, tzinfo=dt_timezone.utc))
        self.assertContains(self.undo(newest), "edited since")

    def test_editors_only(self):
        change = self.move_leg()
        for user in (self.vi, self.co):
            self.client.force_login(user)
            self.assertEqual(self.client.post(reverse("trips:change_undo", args=[self.trip.pk, change.pk])).status_code,
                             403)

    def test_undo_a_section_text_and_a_meal_time(self):
        section = Section.objects.create(day=self.day, section_type="narrative", content={"paragraphs": ["A"]})
        section.content = {"paragraphs": ["A", "B"]}
        section.save()
        self.undo(TripChange.objects.latest("id"))
        section.refresh_from_db()
        self.assertEqual(section.content, {"paragraphs": ["A"]})
        meal = Meal.objects.create(day=self.day, name="Spot", meal_type="dinner")
        meal.reserved_time = time(19, 0)
        meal.save()
        self.undo(TripChange.objects.latest("id"))
        meal.refresh_from_db()
        self.assertIsNone(meal.reserved_time)


class RestoreTests(HistoryFixture):
    def test_restoring_a_deleted_leg_brings_its_links_back(self):
        confirmation = Confirmation.attach_number(self.trip, "DB-1", self.leg, provider="DB")
        task = make_task(self.trip, "Seats", self.leg)
        desk = Contact.objects.create(trip=self.trip, name="DB desk", phone="+49 1")
        ItemLink.link(desk, self.leg)
        pk = self.leg.pk
        with acting_as(self.ed):
            self.leg.delete()
        removed = TripChange.objects.latest("id")
        self.assertEqual(removed.summary, "Removed Frankfurt Hbf → Augsburg Hbf")
        self.client.force_login(self.ed)
        self.assertContains(self.client.get(self.url), "Restore")
        response = self.undo(removed)
        self.assertContains(response, "is back")
        leg = TransportLeg.objects.get(pk=pk)
        self.assertEqual(leg.departure_at, datetime(2027, 9, 19, 8, 0, tzinfo=dt_timezone.utc))
        self.assertTrue(ConfirmationLink.objects.filter(confirmation=confirmation, object_id=pk).exists())
        self.assertEqual([item.pk for item in task.covered()], [pk])  # re-linked (booking-todos K1)
        self.assertTrue(ItemLink.objects.filter(target_id=pk, source_id=desk.pk).exists())
        restored = TripChange.objects.latest("id")
        self.assertEqual((restored.summary, restored.actor), ("Restored Frankfurt Hbf → Augsburg Hbf", self.ed))
        self.assertNotContains(self.client.get(self.url), f'action="/trips/{self.trip.pk}/history/{removed.pk}/undo/"')

    def test_restoring_an_activity_keeps_its_travellers(self):
        ada = Traveler.objects.create(name="Ada")
        activity = TripActivity.objects.create(trip=self.trip, day=self.day, title="Tour", start_time=time(9, 0))
        activity.travelers.add(ada)
        activity.delete()
        self.undo(TripChange.objects.latest("id"))
        self.assertEqual(list(TripActivity.objects.get(title="Tour").travelers.all()), [ada])

    def test_refused_when_its_day_has_gone(self):
        meal = Meal.objects.create(day=self.day2, name="Spot", meal_type="lunch")
        meal.delete()
        removed = TripChange.objects.latest("id")
        self.day2.delete()
        self.assertContains(self.undo(removed), "nowhere to put it back")
        self.assertFalse(Meal.objects.filter(name="Spot").exists())

    def test_days_and_confirmations_are_not_restorable(self):
        Confirmation.objects.create(trip=self.trip, confirmation_number="X").delete()
        self.client.force_login(self.ed)
        self.assertNotContains(self.client.get(self.url), "Restore")


class PruneTests(HistoryFixture):
    def test_sent_changes_older_than_180_days_are_pruned(self):
        old = timezone.now() - timedelta(days=181)
        TripChange.objects.update(when=old, digest_sent_at=old)
        unsent = TripChange.objects.create(trip=self.trip, kind="changed", summary="Not sent yet", when=old)
        call_command("send_trip_digests", stdout=io.StringIO())
        self.assertEqual(list(TripChange.objects.values_list("summary", flat=True)), ["Not sent yet"])
        self.assertTrue(TripChange.objects.filter(pk=unsent.pk).exists())
