from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory, ActivityTag, UserActivityBookmark
from apps.approval_system.models import ApprovalStatus

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


class TagFilterTests(TestCase):
    """One set of tags, on activities (tags plan TG1)."""

    def setUp(self):
        self.category = ActivityCategory.objects.create(name="Hiking", slug="hiking")
        make = lambda name, **kw: Activity.objects.create(  # noqa: E731
            category=self.category, name=name, description="d", visibility="public",
            approval_status=ApprovalStatus.APPROVED, **kw)
        self.ridge, self.lake, self.plain = make("Ridge Walk"), make("Lake Swim"), make("Museum Day")
        hidden = Activity.objects.create(category=self.category, name="Secret Spot", description="d", visibility="private")
        self.outdoor = ActivityTag.objects.create(name="Outdoor")
        self.outdoor.activities.set([self.ridge, self.lake, hidden])
        self.free = ActivityTag.objects.create(name="Free")
        self.free.activities.set([self.ridge])
        ActivityTag.objects.create(name="Unused")
        self.url = reverse("activities:activity_list")

    def test_tag_filters_and_lists_each_once(self):
        names = [a.name for a in self.client.get(self.url, {"tag": "outdoor"}).context["page_obj"]]
        self.assertEqual(sorted(names), ["Lake Swim", "Ridge Walk"])

    def test_select_lists_used_tags_with_public_counts(self):
        response = self.client.get(self.url)
        self.assertEqual([(t.name, t.n) for t in response.context["tags"]], [("Free", 1), ("Outdoor", 2)])
        self.assertContains(response, "Outdoor (2)")
        self.assertNotContains(response, "Unused")

    def test_no_select_while_no_tag_is_used(self):
        ActivityTag.objects.all().delete()
        self.assertNotContains(self.client.get(self.url), 'name="tag"')

    def test_badges_link_to_the_filter(self):
        page = self.client.get(reverse("activities:activity_detail", args=[self.ridge.slug]))
        self.assertContains(page, f'{self.url}?tag=outdoor')


class TagAdminTests(TestCase):
    def test_list_counts_the_activities(self):
        root = User.objects.create_superuser("root", "root@example.com", "pw-1234-abcd")
        category = ActivityCategory.objects.create(name="Hiking", slug="hiking")
        tag = ActivityTag.objects.create(name="Outdoor")
        tag.activities.add(Activity.objects.create(category=category, name="Ridge", description="d"))
        self.client.force_login(root)
        response = self.client.get(reverse("admin:activities_activitytag_changelist"), {"o": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<td class="field-activity_count">1</td>', html=True)
