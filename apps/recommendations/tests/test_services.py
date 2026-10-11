"""Rule-based dashboard suggestions."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country
from apps.recommendations.services import Goals, for_user

TODAY = date.today()


class RecommendationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd")
        self.germany = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU",
                                              continent="Europe", approval_status=ApprovalStatus.APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=self.germany, latitude=48, longitude=11,
                                          approval_status=ApprovalStatus.APPROVED)
        self.festival = ActivityCategory.objects.get(name="Festival")
        self.music = ActivityCategory.objects.get(name="Music")
        self.sports = ActivityCategory.objects.get(name="Sports")

    def activity(self, name, category, **kw):
        return Activity.objects.create(category=category, name=name, description="d", created_by=self.user,
                                       visibility="public", approval_status=ApprovalStatus.APPROVED, **kw)

    def event(self, name, category, days=30, **kw):
        return Event.objects.create(name=name, category=category, description="d", city=self.munich,
                                    start_date=TODAY + timedelta(days=days), approval_status=ApprovalStatus.APPROVED, **kw)

    def test_new_date_for_an_undated_goal_comes_first(self):
        okto = self.activity("Oktoberfest", self.festival)
        self.activity("Popular thing", self.sports, bucket_list_count=50)
        self.event("Oktoberfest 2027", self.festival, related_activity=okto)
        recs = for_user(Goals(activity_ids={okto.pk}, undated_activity_ids={okto.pk}, category_ids={self.festival.pk}))
        self.assertEqual((recs[0]["title"], recs[0]["tag"]), ("Oktoberfest 2027", "New date for your goal"))
        self.assertNotIn("Oktoberfest", [r["title"] for r in recs])  # the activity itself is already a goal

    def test_interests_then_place_then_popular_and_nothing_already_listed(self):
        gig = self.event("Jazz night", self.music)
        listed = self.activity("Already mine", self.music)
        self.activity("Another concert", self.music)
        self.activity("Munich walk", self.sports, country=self.germany)
        self.activity("Crowd favourite", self.sports, bucket_list_count=99)
        recs = for_user(Goals(activity_ids={listed.pk}, event_ids={gig.pk}, category_ids={self.music.pk},
                              country_ids={self.germany.pk}), limit=5)
        self.assertEqual([(r["title"], r["tag"]) for r in recs],
                         [("Another concert", "Matches your interests"), ("Munich walk", "Near your plans"),
                          ("Crowd favourite", "Popular")])

    def test_one_card_per_activity(self):
        bulls = self.activity("Running of the Bulls", self.festival)
        self.event("Running of the Bulls 2027", self.festival, related_activity=bulls)
        titles = [r["title"] for r in for_user(Goals(category_ids={self.festival.pk}), limit=5)]
        self.assertEqual(titles, ["Running of the Bulls 2027"])

    def test_new_user_and_hidden_items(self):
        self.assertEqual(for_user(Goals()), [])
        Activity.objects.create(category=self.music, name="Private", description="d", created_by=self.user, visibility="private")
        Event.objects.create(name="Pending", category=self.music, description="d", city=self.munich,
                             start_date=TODAY + timedelta(days=3), approval_status=ApprovalStatus.PENDING)
        Event.objects.create(name="Past", category=self.music, description="d", city=self.munich,
                             start_date=TODAY - timedelta(days=3), approval_status=ApprovalStatus.APPROVED)
        self.assertEqual(for_user(Goals(category_ids={self.music.pk})), [])
