"""Tests for the staff dashboard.

Two things are worth pinning: that a non-staff reader gets nothing, and that
each figure says what its label says. Counts the traveler/user signals also
touch (accounts, roster linkage) are compared against the ORM rather than
hard-coded — every ``User`` save creates a traveler, so a fixed number there
would be asserting the signal, not the dashboard.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, UserRole
from apps.trips.dashboard import build_dashboard
from apps.trips.models import (
    BookingTask,
    Comment,
    Day,
    Meal,
    Section,
    Traveler,
    Trip,
    TripGrant,
    TripRole,
)

User = get_user_model()


def grant_staff_dashboard(user):
    """The permission that gates /staff/ on this site (``User.can_access_staff``)."""
    user.user_permissions.add(
        Permission.objects.get(
            codename="can_access_staff_dashboard", content_type__app_label="accounts"
        )
    )
    return User.objects.get(pk=user.pk)  # drop the cached permission set


class DashboardAccessTests(TestCase):
    def setUp(self):
        self.staff = grant_staff_dashboard(
            User.objects.create_user("staff", "staff@example.com", "pw-1234", is_staff=True)
        )
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234")

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse("trips_staff:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_non_staff_is_forbidden(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("trips_staff:dashboard")).status_code, 403)

    def test_staff_can_open_it(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("trips_staff:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Site dashboard")

    def test_is_staff_alone_is_forbidden(self):
        # /staff/ is gated by the accounts permission, not by is_staff.
        clerk = User.objects.create_user("clerk", "clerk@example.com", "pw-1234", is_staff=True)
        self.client.force_login(clerk)
        self.assertEqual(self.client.get(reverse("trips_staff:dashboard")).status_code, 403)

    def test_superuser_is_allowed_even_without_is_staff(self):
        boss = User.objects.create_user(
            "boss", "boss@example.com", "pw-1234", is_superuser=True
        )
        self.client.force_login(boss)
        self.assertEqual(self.client.get(reverse("trips_staff:dashboard")).status_code, 200)


class DashboardStatsTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234")
        self.start = date(2027, 9, 17)
        self.europe = Trip.objects.create(
            name="Europe 2027",
            start_date=self.start,
            end_date=date(2027, 10, 3),
            status=Trip.Status.CONFIRMING,
        )
        self.taos = Trip.objects.create(
            name="Taos 2026",
            start_date=date(2026, 9, 12),
            end_date=date(2026, 9, 20),
            status=Trip.Status.READY_TO_GO,
        )

    def test_trips_by_status_and_total(self):
        stats = build_dashboard()
        self.assertEqual(stats["trips"]["total"], 2)
        by_status = {
            row["value"]: row["count"] for row in stats["trips"]["by_status"]
        }
        self.assertEqual(by_status[Trip.Status.CONFIRMING], 1)
        self.assertEqual(by_status[Trip.Status.READY_TO_GO], 1)
        self.assertEqual(by_status[Trip.Status.STARTING], 0)
        self.assertEqual(by_status[Trip.Status.FLESHING_OUT], 0)

    def test_deleted_trip_leaves_the_live_total(self):
        self.taos.soft_delete()
        stats = build_dashboard()
        self.assertEqual(stats["trips"]["total"], 1)
        self.assertEqual(stats["trips"]["deleted"], 1)

    def test_task_counts_and_overdue(self):
        BookingTask.objects.create(
            trip=self.europe,
            title="Book flights",
            priority=BookingTask.Priority.CRITICAL,
            due=date(2020, 1, 1),
        )
        BookingTask.objects.create(trip=self.europe, title="Pack")
        BookingTask.objects.create(trip=self.europe, title="Old", done=True)
        stats = build_dashboard()
        self.assertEqual(stats["tasks"]["total"], 3)
        self.assertEqual(stats["tasks"]["outstanding"], 2)
        self.assertEqual(stats["tasks"]["completed"], 1)
        self.assertEqual(stats["tasks"]["overdue"], 1)
        self.assertEqual(stats["tasks"]["trips_with_outstanding"], 1)
        by_priority = {
            row["value"]: row["count"] for row in stats["tasks"]["by_priority"]
        }
        self.assertEqual(by_priority[BookingTask.Priority.CRITICAL], 1)
        self.assertEqual(by_priority[BookingTask.Priority.MEDIUM], 1)
        self.assertEqual(by_priority[BookingTask.Priority.LOW], 0)

    def test_done_past_due_task_is_not_overdue(self):
        BookingTask.objects.create(
            trip=self.europe,
            title="Already handled",
            due=date(2020, 1, 1),
            done=True,
        )
        self.assertEqual(build_dashboard()["tasks"]["overdue"], 0)

    def test_grants_and_trips_without_grants(self):
        TripGrant.objects.create(trip=self.europe, user=self.alice)
        stats = build_dashboard()
        self.assertEqual(stats["access"]["grants"], 1)
        self.assertEqual(stats["access"]["users_with_grants"], 1)
        self.assertEqual(stats["trips"]["without_grants"], 1)

    def test_trip_access_is_counted_by_grant_role(self):
        bob = User.objects.create_user("bob", "bob@example.com", "pw-1234")
        TripGrant.objects.create(trip=self.europe, user=self.alice, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.taos, user=self.alice, role=TripRole.VIEWER)
        TripGrant.objects.create(trip=self.europe, user=bob, role=TripRole.VIEWER)
        UserRole.objects.create(user=bob, role=Role.CREATOR)
        stats = build_dashboard()
        counts = {row["label"]: row["count"] for row in stats["roles"]}
        self.assertEqual(counts["Viewer"], 2)
        self.assertEqual(counts["Editor"], 1)
        self.assertEqual(counts["Commentor"], 0)
        self.assertEqual(stats["creators"], 1)
        self.assertEqual(
            stats["users_without_role"],
            User.objects.filter(trip_grants__isnull=True).count(),
        )

    def test_unowned_trips_are_counted(self):
        self.assertEqual(build_dashboard()["trips"]["unowned"], 2)
        self.europe.created_by = self.alice
        self.europe.save(update_fields=["created_by"])
        self.assertEqual(build_dashboard()["trips"]["unowned"], 1)

    def test_content_totals_and_section_types(self):
        day = Day.objects.create(
            trip=self.europe, day_number=1, date=self.start
        )
        Section.objects.create(
            day=day, section_type=Section.Type.CALLOUT, content={"text": "a"}
        )
        Section.objects.create(
            day=day, section_type=Section.Type.CALLOUT, content={"text": "b"}
        )
        Section.objects.create(
            day=day, section_type=Section.Type.FREE_TEXT, content={}
        )
        Meal.objects.create(
            day=day, name="Cafe", meal_type=Meal.MealType.LUNCH, price_range="$$"
        )
        Comment.objects.create(
            author=self.alice,
            content_type=ContentType.objects.get_for_model(Trip),
            object_id=self.europe.pk,
            body="Looks good",
        )
        stats = build_dashboard()
        self.assertEqual(stats["content"]["days"], 1)
        self.assertEqual(stats["content"]["sections"], 3)
        self.assertEqual(stats["content"]["meals"], 1)
        self.assertEqual(stats["content"]["comments"], 1)
        self.assertEqual(stats["content"]["comments_recent"], 1)
        by_type = {
            row["value"]: row["count"] for row in stats["sections_by_type"]
        }
        self.assertEqual(by_type[Section.Type.CALLOUT], 2)
        self.assertEqual(by_type[Section.Type.FREE_TEXT], 1)
        self.assertEqual(by_type[Section.Type.PHASE], 0)

    def test_roster_linkage_is_counted(self):
        Traveler.objects.create(name="Unlinked Person")
        stats = build_dashboard()
        self.assertEqual(
            stats["travelers"]["total"], Traveler.objects.count()
        )
        self.assertEqual(
            stats["travelers"]["linked"],
            Traveler.objects.filter(user__isnull=False).count(),
        )
        self.assertEqual(
            stats["travelers"]["unlinked"],
            Traveler.objects.filter(user__isnull=True).count(),
        )
        self.assertGreaterEqual(stats["travelers"]["linked"], 1)

    def test_recent_trips_are_annotated_not_property(self):
        BookingTask.objects.create(trip=self.europe, title="One")
        BookingTask.objects.create(trip=self.europe, title="Two")
        BookingTask.objects.create(trip=self.europe, title="Done", done=True)
        recent = build_dashboard()["recent_trips"]
        europe = next(t for t in recent if t.pk == self.europe.pk)
        self.assertEqual(europe.outstanding_task_count, 2)
