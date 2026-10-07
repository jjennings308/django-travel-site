from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory, UserActivityBookmark

User = get_user_model()


class ActivityPageTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", "owner@example.com", "pw-1234-abcd")
        self.category = ActivityCategory.objects.create(name="Hiking", slug="hiking", allow_user_submissions=True)
        self.activity = Activity.objects.create(
            category=self.category, name="Ridge Walk", description="A long walk.",
            created_by=self.owner, visibility="private",
        )
        self.client.force_login(self.owner)

    def url(self, name):
        return reverse(f"activities:{name}", args=[self.activity.slug])

    def test_quick_add_creates_and_goes_to_the_full_form(self):
        self.assertContains(self.client.get(reverse("activities:activity_quick_add")), "Quick Add Activity")
        response = self.client.post(reverse("activities:activity_quick_add"), {
            "category": self.category.pk, "name": "Lake Swim", "description": "Cold.", "visibility": "private",
        })
        created = Activity.objects.get(name="Lake Swim")
        self.assertRedirects(response, reverse("activities:activity_edit", args=[created.slug]))

    def test_bookmarks_list_and_remove(self):
        self.assertContains(self.client.get(reverse("activities:my_bookmarks")), "No bookmarks yet")
        self.client.post(self.url("activity_bookmark"))
        self.assertContains(self.client.get(reverse("activities:my_bookmarks")), "Ridge Walk")
        self.client.post(self.url("activity_unbookmark"))
        self.assertFalse(UserActivityBookmark.objects.exists())

    def test_detail_offers_the_owner_actions(self):
        response = self.client.get(self.url("activity_detail"))
        for name in ["activity_edit", "activity_delete", "activity_submit_for_public", "activity_bookmark"]:
            self.assertContains(response, self.url(name))

    def test_submit_for_public(self):
        self.assertContains(self.client.get(self.url("activity_submit_for_public")), "Make this activity public?")
        self.client.post(self.url("activity_submit_for_public"))
        self.activity.refresh_from_db()
        self.assertEqual((self.activity.visibility, self.activity.approval_status), ("public", "pending"))

    def test_make_private(self):
        self.client.post(self.url("activity_submit_for_public"))
        self.assertContains(self.client.get(self.url("activity_make_private")), "Make this activity private?")
        self.client.post(self.url("activity_make_private"))
        self.activity.refresh_from_db()
        self.assertEqual((self.activity.visibility, self.activity.approval_status), ("private", "draft"))

    def test_delete(self):
        self.assertContains(self.client.get(self.url("activity_delete")), "Delete this activity?")
        self.assertRedirects(self.client.post(self.url("activity_delete")), reverse("activities:my_activities"))
        self.assertFalse(Activity.objects.filter(pk=self.activity.pk).exists())
