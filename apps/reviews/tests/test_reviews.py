from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City, Country
from apps.notifications.models import Notification
from apps.reviews.models import Review, ReviewReport

User = get_user_model()


class ReviewFixture(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", "alice@example.com", "pw-1234-abcd")
        self.bob = User.objects.create_user("bob", "bob@example.com", "pw-1234-abcd")
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe")
        self.city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=2,
                                        approval_status=ApprovalStatus.APPROVED)
        self.poi = POI.objects.create(name="Old Bridge", slug="old-bridge", city=self.city, latitude=1, longitude=2,
                                      approval_status=ApprovalStatus.APPROVED)
        cat = ActivityCategory.objects.create(name="Hiking", slug="hiking")
        self.activity = Activity.objects.create(category=cat, name="Ridge Walk", description="d", created_by=self.bob,
                                                visibility="public", approval_status=ApprovalStatus.APPROVED)
        self.event = Event.objects.create(name="Jazz Night", category=cat, description="d", city=self.city,
                                          start_date=date.today() + timedelta(days=9), approval_status=ApprovalStatus.APPROVED)
        self.targets = {"activity": self.activity, "event": self.event, "city": self.city, "poi": self.poi}

    def write(self, kind, obj, rating=4, comment="Lovely.", user=None):
        self.client.force_login(user or self.alice)
        return self.client.post(reverse("reviews:write", args=[kind, obj.slug]),
                                {"rating": rating, "title": "", "comment": comment, "visit_date": ""})


class WriteTests(ReviewFixture):
    def test_review_each_kind_once_and_edit(self):
        pages = {"activity": "activities:activity_detail", "event": "events:event_detail",
                 "city": "locations:city_detail", "poi": "locations:poi_detail"}
        for kind, obj in self.targets.items():
            with self.subTest(kind=kind):
                response = self.write(kind, obj, rating=5)
                self.assertRedirects(response, reverse(pages[kind], args=[obj.slug]) + "#reviews", fetch_redirect_response=False)
                self.write(kind, obj, rating=3, comment="On reflection, fine.")  # edits, no duplicate
                reviews = [r for r in Review.objects.filter(user=self.alice) if r.target == obj]
                self.assertEqual(len(reviews), 1)
                self.assertEqual((reviews[0].rating, reviews[0].comment), (3, "On reflection, fine."))
                obj.refresh_from_db()
                self.assertEqual((obj.average_rating, obj.review_count), (Decimal("3.00"), 1))

    def test_average_over_members(self):
        self.write("city", self.city, rating=5)
        self.write("city", self.city, rating=4, user=self.bob)
        self.city.refresh_from_db()
        self.assertEqual((self.city.average_rating, self.city.review_count), (Decimal("4.50"), 2))

    def test_login_required(self):
        url = reverse("reviews:write", args=["city", self.city.slug])
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_unpublished_or_unknown_target_is_404(self):
        self.client.force_login(self.alice)
        self.event.approval_status = ApprovalStatus.PENDING
        self.event.save()
        self.assertEqual(self.client.get(reverse("reviews:write", args=["event", self.event.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("reviews:for_target", args=["event", self.event.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("reviews:write", args=["trip", "x"])).status_code, 404)

    def test_rating_is_required(self):
        self.client.force_login(self.alice)
        self.client.post(reverse("reviews:write", args=["city", self.city.slug]), {"rating": "", "comment": "x"})
        self.assertFalse(Review.objects.exists())

    def test_only_the_author_deletes(self):
        self.write("city", self.city)
        review = Review.objects.get()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(reverse("reviews:delete", args=[review.pk])).status_code, 404)
        self.client.force_login(self.alice)
        self.client.post(reverse("reviews:delete", args=[review.pk]))
        self.assertFalse(Review.objects.exists())
        self.city.refresh_from_db()
        self.assertEqual((self.city.average_rating, self.city.review_count), (None, 0))


class ListTests(ReviewFixture):
    def test_fragment_lists_visible_reviews_only(self):
        self.write("poi", self.poi, comment="Great views from the middle.")
        self.write("poi", self.poi, comment="Spam spam spam.", user=self.bob)
        Review.objects.filter(user=self.bob).update(is_approved=False)
        self.client.logout()
        page = self.client.get(reverse("reviews:for_target", args=["poi", self.poi.slug]))
        self.assertContains(page, "Great views from the middle.")
        self.assertNotContains(page, "Spam spam spam.")
        self.assertContains(page, "Log in to write a review")

    def test_hiding_recounts(self):
        self.write("city", self.city, rating=5)
        self.write("city", self.city, rating=1, user=self.bob)
        review = Review.objects.get(user=self.bob)
        review.is_approved = False
        review.save()
        self.city.refresh_from_db()
        self.assertEqual((self.city.average_rating, self.city.review_count), (Decimal("5.00"), 1))

    def test_detail_pages_carry_the_reviews_card(self):
        self.write("city", self.city, rating=4)
        page = self.client.get(reverse("locations:city_detail", args=[self.city.slug]))
        self.assertContains(page, reverse("reviews:for_target", args=["city", self.city.slug]))
        page = self.client.get(reverse("activities:activity_detail", args=[self.activity.slug]))
        self.assertContains(page, reverse("reviews:for_target", args=["activity", self.activity.slug]))

    def test_header_shows_stars(self):
        self.write("activity", self.activity, rating=4)
        page = self.client.get(reverse("activities:activity_detail", args=[self.activity.slug]))
        self.assertContains(page, "(1 review)")


class ReportTests(ReviewFixture):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user("staff", "staff@example.com", "pw-1234-abcd")
        self.staff.user_permissions.add(Permission.objects.get(codename="can_access_staff_dashboard"))
        self.write("city", self.city, rating=1, user=self.bob)
        self.review = Review.objects.get()

    def report(self, user):
        self.client.force_login(user)
        return self.client.post(reverse("reviews:report", args=[self.review.pk]), {"reason": "spam", "details": ""})

    def test_report_notifies_staff_once_per_member(self):
        self.report(self.alice)
        self.report(self.alice)
        self.assertEqual(ReviewReport.objects.count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.staff, notification_type__name="review_reported").count(), 1)
        self.review.refresh_from_db()
        self.assertTrue(self.review.is_approved)
        self.assertEqual(self.review.report_count, 1)

    def test_cannot_report_own_review(self):
        self.report(self.bob)
        self.assertFalse(ReviewReport.objects.exists())

    def test_three_reports_hide_it(self):
        for name in ("r1", "r2", "r3"):
            self.report(User.objects.create_user(name, f"{name}@example.com", "pw-1234-abcd"))
        self.review.refresh_from_db()
        self.assertFalse(self.review.is_approved)
        self.city.refresh_from_db()
        self.assertEqual(self.city.review_count, 0)

    def test_staff_dashboard_lists_it(self):
        self.report(self.alice)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("pages:staff_dashboard")), "Reported reviews")
