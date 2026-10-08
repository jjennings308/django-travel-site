from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.bucketlists.models import BucketListCategory, BucketListItem
from apps.events.models import Event, EventCategory
from apps.locations.models import POI, City, Country

User = get_user_model()


class BucketFixture(TestCase):
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
        self.event = Event.objects.create(name="Jazz Night", category=EventCategory.objects.get(name="Music"),
                                          description="d", city=self.city, start_date=date.today() + timedelta(days=9),
                                          approval_status=ApprovalStatus.APPROVED)
        self.client.force_login(self.alice)


class AddTests(BucketFixture):
    def test_custom_goal(self):
        response = self.client.post(reverse("bucketlists:item_add"), {
            "custom_title": "See the northern lights", "status": "wishlist", "priority": 5})
        self.assertRedirects(response, reverse("bucketlists:dashboard"))
        item = BucketListItem.objects.get(user=self.alice)
        self.assertEqual((item.title, item.kind, item.is_public), ("See the northern lights", "custom", False))

    def test_custom_goal_needs_a_title(self):
        self.client.post(reverse("bucketlists:item_add"), {"custom_title": "", "status": "wishlist", "priority": 3})
        self.assertFalse(BucketListItem.objects.exists())

    def test_quick_add_each_kind_once(self):
        for kind, obj in [("activity", self.activity), ("city", self.city), ("poi", self.poi), ("event", self.event)]:
            with self.subTest(kind=kind):
                url = reverse("bucketlists:quick_add", args=[kind, obj.pk])
                first = self.client.post(url)
                item = BucketListItem.objects.get(user=self.alice, **{kind: obj})
                self.assertRedirects(first, reverse("bucketlists:item_edit", args=[item.pk]))
                self.client.post(url)  # second click: no duplicate
                self.assertEqual(BucketListItem.objects.filter(user=self.alice, **{kind: obj}).count(), 1)
                self.assertEqual((item.kind, item.title), (kind, obj.name))

    def test_cannot_add_hidden_things(self):
        self.event.approval_status = ApprovalStatus.PENDING
        self.event.save()
        self.assertEqual(self.client.post(reverse("bucketlists:quick_add", args=["event", self.event.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("bucketlists:quick_add", args=["nonsense", 1])).status_code, 404)

    def test_quick_add_is_post_only(self):
        self.assertEqual(self.client.get(reverse("bucketlists:quick_add", args=["city", self.city.pk])).status_code, 405)

    def test_bucket_list_count_kept_in_step(self):
        self.client.post(reverse("bucketlists:quick_add", args=["activity", self.activity.pk]))
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.bucket_list_count, 1)
        BucketListItem.objects.get(activity=self.activity).delete()
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.bucket_list_count, 0)


class ItemTests(BucketFixture):
    def setUp(self):
        super().setUp()
        self.item = BucketListItem.objects.create(user=self.alice, custom_title="Learn to surf")

    def test_dashboard_lists_own_items_with_progress(self):
        BucketListItem.objects.create(user=self.alice, custom_title="Done thing", status="completed", completed_date=date.today())
        BucketListItem.objects.create(user=self.bob, custom_title="Bob's secret")
        response = self.client.get(reverse("bucketlists:dashboard"))
        self.assertContains(response, "Learn to surf")
        self.assertNotContains(response, "Bob&#x27;s secret")
        self.assertContains(response, "50%")

    def test_other_users_items_are_404(self):
        self.client.force_login(self.bob)
        for name in ["item_edit", "item_complete", "item_delete"]:
            self.assertEqual(self.client.get(reverse(f"bucketlists:{name}", args=[self.item.pk])).status_code, 404)

    def test_complete(self):
        self.client.post(reverse("bucketlists:item_complete", args=[self.item.pk]),
                         {"completed_date": "2026-09-01", "user_rating": "5", "completion_notes": "Cold but great"})
        self.item.refresh_from_db()
        self.assertEqual((self.item.status, str(self.item.completed_date), self.item.user_rating), ("completed", "2026-09-01", 5))

    def test_edit_and_categories(self):
        cat = BucketListCategory.objects.create(user=self.alice, name="Ocean")
        self.client.post(reverse("bucketlists:item_edit", args=[self.item.pk]), {
            "custom_title": "Learn to surf", "status": "planning", "priority": 4, "categories": [cat.pk], "is_public": "on"})
        self.item.refresh_from_db()
        self.assertEqual((self.item.status, self.item.is_public, list(self.item.categories.all())), ("planning", True, [cat]))
        self.assertContains(self.client.get(reverse("bucketlists:dashboard") + f"?category={cat.pk}"), "Learn to surf")

    def test_cannot_use_someone_elses_category(self):
        bobs = BucketListCategory.objects.create(user=self.bob, name="Bob's")
        self.client.post(reverse("bucketlists:item_edit", args=[self.item.pk]), {
            "custom_title": "Learn to surf", "status": "wishlist", "priority": 3, "categories": [bobs.pk]})
        self.assertEqual(self.item.categories.count(), 0)

    def test_delete(self):
        self.client.post(reverse("bucketlists:item_delete", args=[self.item.pk]))
        self.assertFalse(BucketListItem.objects.filter(pk=self.item.pk).exists())


class CategoryTests(BucketFixture):
    def test_create_rename_delete(self):
        self.client.post(reverse("bucketlists:categories"), {"name": "Europe", "color": "#123456"})
        cat = BucketListCategory.objects.get(user=self.alice)
        self.client.post(reverse("bucketlists:category_edit", args=[cat.pk]), {"name": "Europe 2027", "color": "#123456"})
        cat.refresh_from_db()
        self.assertEqual(cat.name, "Europe 2027")
        self.client.post(reverse("bucketlists:category_edit", args=[cat.pk]), {"delete": "1"})
        self.assertFalse(BucketListCategory.objects.exists())

    def test_duplicate_name_rejected(self):
        BucketListCategory.objects.create(user=self.alice, name="Europe")
        response = self.client.post(reverse("bucketlists:categories"), {"name": "europe", "color": "#123456"})
        self.assertContains(response, "already have a category")


class PublicPageTests(BucketFixture):
    def setUp(self):
        super().setUp()
        BucketListItem.objects.create(user=self.alice, custom_title="Shared goal", is_public=True)
        BucketListItem.objects.create(user=self.alice, custom_title="Private goal", is_public=False)
        self.url = reverse("bucketlists:public_list", args=["alice"])

    def test_public_profile_shows_only_public_items(self):
        self.alice.profile_visibility = "public"
        self.alice.save()
        self.client.logout()
        response = self.client.get(self.url)
        self.assertContains(response, "Shared goal")
        self.assertNotContains(response, "Private goal")

    def test_private_profile_is_404_to_others_but_owner_sees_it(self):
        self.alice.profile_visibility = "private"
        self.alice.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.alice)
        self.assertContains(self.client.get(self.url), "only you can see it")


class ButtonTests(BucketFixture):
    def test_detail_pages_offer_the_button(self):
        pages = [(reverse("activities:activity_detail", args=[self.activity.slug]), "activity", self.activity),
                 (reverse("events:event_detail", args=[self.event.slug]), "event", self.event),
                 (reverse("locations:city_detail", args=[self.city.slug]), "city", self.city),
                 (reverse("locations:poi_detail", args=[self.poi.slug]), "poi", self.poi)]
        for url, kind, obj in pages:
            with self.subTest(kind=kind):
                self.assertContains(self.client.get(url), reverse("bucketlists:quick_add", args=[kind, obj.pk]))

    def test_no_button_when_signed_out(self):
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("events:event_detail", args=[self.event.slug])), "Add to bucket list")
