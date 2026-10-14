from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.bucketlists.models import BucketListCategory, BucketListItem
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region
from apps.trips.models import Trip, TripGrant, TripRole

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
        self.event = Event.objects.create(name="Jazz Night", category=ActivityCategory.objects.get(name="Music"),
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
                field = "pois" if kind == "poi" else kind
                item = BucketListItem.objects.get(user=self.alice, **{field: obj})
                self.assertRedirects(first, reverse("bucketlists:item_edit", args=[item.pk]))
                self.client.post(url)  # second click: no duplicate
                self.assertEqual(BucketListItem.objects.filter(user=self.alice, **{field: obj}).count(), 1)
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


class LifecycleTests(BucketFixture):
    """idea -> dated -> trip -> done, for activity, POI and custom items."""

    def setUp(self):
        super().setUp()
        self.okto = Activity.objects.create(category=ActivityCategory.objects.get(name="Festival"), name="Oktoberfest",
                                            description="d", created_by=self.bob, visibility="public",
                                            approval_status=ApprovalStatus.APPROVED)
        self.okto_2027 = Event.objects.create(
            name="Oktoberfest 2027", category=self.okto.category, related_activity=self.okto, description="d",
            city=self.city, start_date=date(2027, 9, 18), end_date=date(2027, 10, 3),
            approval_status=ApprovalStatus.APPROVED)
        self.fountain = POI.objects.create(name="Fountain", slug="fountain", city=self.city, latitude=1, longitude=2,
                                           approval_status=ApprovalStatus.APPROVED)

    def edit(self, item, **data):
        base = {"status": item.status, "priority": item.priority}
        return self.client.post(reverse("bucketlists:item_edit", args=[item.pk]), {**base, **data})

    def test_activity_item_gets_dated_by_picking_an_event(self):
        self.client.post(reverse("bucketlists:quick_add", args=["activity", self.okto.pk]))
        item = BucketListItem.objects.get(user=self.alice)
        self.assertEqual((item.kind, item.stage), ("activity", "idea"))
        page = self.client.get(reverse("bucketlists:item_edit", args=[item.pk]))
        self.assertContains(page, "Oktoberfest 2027")  # offered as a date
        self.assertNotContains(page, "Jazz Night")  # not a date of this activity
        self.edit(item, event=self.okto_2027.pk)
        item.refresh_from_db()
        self.assertEqual((item.kind, item.event, item.stage), ("activity", self.okto_2027, "dated"))
        self.okto_2027.refresh_from_db()
        self.assertEqual(self.okto_2027.bucket_list_count, 1)  # counted when the date is picked, not only on create

    def test_cannot_pick_another_activitys_event(self):
        item = BucketListItem.objects.create(user=self.alice, activity=self.okto)
        self.edit(item, event=self.event.pk)
        item.refresh_from_db()
        self.assertIsNone(item.event)

    def test_adding_an_event_dates_the_activity_item(self):
        item = BucketListItem.objects.create(user=self.alice, activity=self.okto)
        self.client.post(reverse("bucketlists:quick_add", args=["event", self.okto_2027.pk]))
        self.assertEqual(BucketListItem.objects.filter(user=self.alice).count(), 1)
        item.refresh_from_db()
        self.assertEqual(item.event, self.okto_2027)

    def test_adding_an_event_of_an_activity_starts_an_activity_item(self):
        self.client.post(reverse("bucketlists:quick_add", args=["event", self.okto_2027.pk]))
        item = BucketListItem.objects.get(user=self.alice)
        self.assertEqual((item.activity, item.event, item.kind, item.title), (self.okto, self.okto_2027, "activity", "Oktoberfest"))

    def test_poi_item_holds_several_pois_and_target_dates(self):
        self.client.post(reverse("bucketlists:quick_add", args=["poi", self.poi.pk]))
        item = BucketListItem.objects.get(user=self.alice)
        self.assertContains(self.client.get(reverse("bucketlists:item_edit", args=[item.pk])), "Fountain")
        self.edit(item, pois=[self.poi.pk, self.fountain.pk], custom_title="", target_date="2027-06-01",
                  target_end_date="2027-06-05")
        item = BucketListItem.objects.get(pk=item.pk)
        self.assertEqual(set(item.pois.all()), {self.poi, self.fountain})
        self.assertEqual((item.kind, item.stage, item.place), ("poi", "dated", "Testville"))
        self.assertIn("Fountain", item.title)
        self.assertEqual(item.dates, (date(2027, 6, 1), date(2027, 6, 5)))
        # the POI page's button now finds this item rather than starting another
        self.client.post(reverse("bucketlists:quick_add", args=["poi", self.fountain.pk]))
        self.assertEqual(BucketListItem.objects.filter(user=self.alice).count(), 1)

    def test_poi_item_needs_a_poi(self):
        item = BucketListItem.objects.create(user=self.alice)
        item.pois.add(self.poi)
        self.edit(item, pois=[])
        self.assertEqual(list(item.pois.all()), [self.poi])

    def test_end_date_before_start_is_refused(self):
        item = BucketListItem.objects.create(user=self.alice, custom_title="Surf")
        response = self.edit(item, custom_title="Surf", target_date="2027-06-05", target_end_date="2027-06-01")
        self.assertContains(response, "before the start date")

    def test_plan_a_trip_from_an_event_dated_item(self):
        """Any signed-in user (alice has no creator role) can start a trip from their item."""
        item = BucketListItem.objects.create(user=self.alice, activity=self.okto, event=self.okto_2027)
        url = reverse("bucketlists:plan_trip", args=[item.pk])
        page = self.client.get(url)
        self.assertContains(page, 'value="2027-09-18"')
        self.assertContains(page, 'value="2027-10-03"')
        self.assertContains(page, "Testville, Testland")
        response = self.client.post(url, {"name": "Oktoberfest 2027", "destination": "Testville, Testland",
                                          "start_date": "2027-09-18", "end_date": "2027-10-03"})
        trip = Trip.objects.get()
        self.assertRedirects(response, reverse("trips:trip_edit", args=[trip.pk]))
        self.assertEqual((trip.created_by, trip.start_date), (self.alice, date(2027, 9, 18)))
        self.assertEqual(TripGrant.objects.get(trip=trip).role, TripRole.EDITOR)
        self.assertTrue(trip.travelers.filter(user=self.alice).exists())
        item.refresh_from_db()
        self.assertEqual((item.trip, item.stage, item.status), (trip, "trip", "planning"))
        self.assertEqual(self.client.get(reverse("trips:trip_detail", args=[trip.pk])).status_code, 200)
        # a second visit goes to the trip instead of starting another
        self.assertRedirects(self.client.get(url), reverse("trips:trip_detail", args=[trip.pk]))
        self.assertEqual(Trip.objects.count(), 1)

    def test_plan_a_trip_from_an_undated_activity_uses_its_place(self):
        self.okto.city = self.city
        self.okto.save()
        item = BucketListItem.objects.create(user=self.alice, activity=self.okto)
        self.assertContains(self.client.get(reverse("bucketlists:plan_trip", args=[item.pk])), "Testville, Testland")

    def test_plan_a_trip_needs_dates_and_ownership(self):
        item = BucketListItem.objects.create(user=self.alice, custom_title="Surf")
        url = reverse("bucketlists:plan_trip", args=[item.pk])
        self.client.post(url, {"name": "Surf", "start_date": "2027-06-05", "end_date": "2027-06-01"})
        self.assertFalse(Trip.objects.exists())
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_deleted_trip_falls_back_a_stage(self):
        trip = Trip.objects.create(name="T", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        item = BucketListItem.objects.create(user=self.alice, custom_title="Surf", target_date=date(2027, 1, 1), trip=trip)
        self.assertEqual(item.stage, "trip")
        trip.soft_delete()
        item = BucketListItem.objects.get(pk=item.pk)
        self.assertEqual(item.stage, "dated")
        self.assertContains(self.client.get(reverse("bucketlists:dashboard")), reverse("bucketlists:plan_trip", args=[item.pk]))

    def test_dashboard_shows_stage_and_trip_link(self):
        trip = Trip.objects.create(name="Surf trip", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        TripGrant.objects.create(trip=trip, user=self.alice, role=TripRole.EDITOR)
        BucketListItem.objects.create(user=self.alice, custom_title="Surf", trip=trip)
        page = self.client.get(reverse("bucketlists:dashboard"))
        self.assertContains(page, "Trip planned")
        self.assertContains(page, reverse("trips:trip_detail", args=[trip.pk]))


class GoalCatalogueTests(BucketFixture):
    """Steering "Add a goal" toward the catalogue, and linking a goal afterwards."""

    def setUp(self):
        super().setUp()
        self.goal = BucketListItem.objects.create(
            user=self.alice, custom_title="Walk the ridge", custom_description="With the dog",
            personal_notes="Spring", target_date=date(2027, 4, 1), status="researching")
        cat = BucketListCategory.objects.create(user=self.alice, name="Outdoors")
        self.goal.categories.add(cat)

    def suggest(self, q):
        return self.client.get(reverse("bucketlists:suggest"), {"q": q}).json()["results"]

    def test_suggest_finds_visible_catalogue_entries(self):
        names = {(r["kind"], r["name"]) for r in self.suggest("ridge walk")}
        self.assertEqual(names, {("activity", "Ridge Walk")})
        self.assertEqual({r["kind"] for r in self.suggest("test")}, {"city"})
        self.assertEqual(self.suggest("bridge")[0]["add_url"], reverse("bucketlists:item_add") + f"?poi={self.poi.pk}")
        self.assertEqual(self.suggest("ri"), [])  # too short

    def test_suggest_hides_unapproved_entries(self):
        self.activity.approval_status = ApprovalStatus.PENDING
        self.activity.save()
        self.event.approval_status = ApprovalStatus.PENDING
        self.event.created_by = self.bob
        self.event.save()
        self.assertEqual(self.suggest("ridge walk"), [])
        self.assertEqual(self.suggest("jazz"), [])

    def test_add_page_offers_suggestions_and_edit_page_the_link_box(self):
        self.assertContains(self.client.get(reverse("bucketlists:item_add")), reverse("bucketlists:suggest"))
        self.assertContains(self.client.get(reverse("bucketlists:item_edit", args=[self.goal.pk])), "Link to the catalogue")

    def test_link_goal_to_activity_keeps_everything(self):
        self.client.post(reverse("bucketlists:link_item", args=[self.goal.pk]), {"target": f"activity:{self.activity.pk}"})
        item = BucketListItem.objects.get(pk=self.goal.pk)
        self.assertEqual((item.kind, item.title, item.custom_title, item.custom_description), ("activity", "Ridge Walk", "", ""))
        self.assertEqual((item.personal_notes, item.target_date, item.status), ("Spring\n\nWith the dog", date(2027, 4, 1), "researching"))
        self.assertEqual(item.categories.count(), 1)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.bucket_list_count, 1)
        self.assertNotContains(self.client.get(reverse("bucketlists:item_edit", args=[item.pk])), "Link to the catalogue")
        item.delete()
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.bucket_list_count, 0)

    def test_link_goal_to_poi_keeps_its_name(self):
        self.client.post(reverse("bucketlists:link_item", args=[self.goal.pk]), {"target": f"poi:{self.poi.pk}"})
        item = BucketListItem.objects.get(pk=self.goal.pk)
        self.assertEqual((item.kind, item.title, list(item.pois.all())), ("poi", "Walk the ridge", [self.poi]))

    def test_link_refuses_a_duplicate(self):
        BucketListItem.objects.create(user=self.alice, city=self.city)
        self.client.post(reverse("bucketlists:link_item", args=[self.goal.pk]), {"target": f"city:{self.city.pk}"})
        self.goal.refresh_from_db()
        self.assertEqual((self.goal.kind, self.goal.custom_title), ("custom", "Walk the ridge"))

    def test_link_is_owner_only_and_checks_the_target(self):
        url = reverse("bucketlists:link_item", args=[self.goal.pk])
        self.assertEqual(self.client.post(url, {"target": "nonsense:1"}).status_code, 404)
        self.event.approval_status = ApprovalStatus.PENDING
        self.event.created_by = self.bob
        self.event.save()
        self.assertEqual(self.client.post(url, {"target": f"event:{self.event.pk}"}).status_code, 404)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url, {"target": f"city:{self.city.pk}"}).status_code, 404)


class MyDatesTests(BucketFixture):
    """Stage 3: dated goals soonest first, undated ones with their activity's upcoming events."""

    def setUp(self):
        super().setUp()
        self.later = Event.objects.create(name="Ridge Walk Day", category=self.activity.category, description="d",
                                          related_activity=self.activity, city=self.city,
                                          start_date=date.today() + timedelta(days=40), approval_status=ApprovalStatus.APPROVED)
        self.url = reverse("bucketlists:dates")

    def test_sections(self):
        soon = BucketListItem.objects.create(user=self.alice, custom_title="Surf", target_date=date.today() + timedelta(days=3))
        BucketListItem.objects.create(user=self.alice, custom_title="Old goal", target_date=date.today() - timedelta(days=30))
        BucketListItem.objects.create(user=self.alice, activity=self.activity)
        BucketListItem.objects.create(user=self.alice, custom_title="Done goal", status="completed", target_date=date.today())
        BucketListItem.objects.create(user=self.bob, custom_title="Bob goal", target_date=date.today())
        page = self.client.get(self.url)
        self.assertEqual([i.title for i in page.context["dated"]], ["Surf"])
        self.assertEqual([i.title for i in page.context["past"]], ["Old goal"])
        self.assertEqual([i.title for i in page.context["undated"]], ["Ridge Walk"])
        self.assertEqual(page.context["undated"][0].date_options, [self.later])
        self.assertContains(page, reverse("bucketlists:plan_trip", args=[soon.pk]))
        self.assertNotContains(page, "Bob goal")
        self.assertNotContains(page, "Done goal")

    def test_pick_a_date(self):
        item = BucketListItem.objects.create(user=self.alice, activity=self.activity)
        response = self.client.post(reverse("bucketlists:pick_date", args=[item.pk]), {"event": self.later.pk})
        self.assertRedirects(response, self.url)
        item.refresh_from_db()
        self.assertEqual((item.event, item.stage), (self.later, "dated"))

    def test_pick_date_must_be_of_the_activity_and_yours(self):
        item = BucketListItem.objects.create(user=self.alice, activity=self.activity)
        url = reverse("bucketlists:pick_date", args=[item.pk])
        self.assertEqual(self.client.post(url, {"event": self.event.pk}).status_code, 404)  # Jazz Night: other activity
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(url, {"event": self.later.pk}).status_code, 404)


class TripDoneTests(BucketFixture):
    """Ticking off a finished trip from its page."""

    def setUp(self):
        super().setUp()
        self.trip = Trip.objects.create(name="Surf week", start_date=date.today() - timedelta(days=10),
                                        end_date=date.today() - timedelta(days=3))
        TripGrant.objects.create(trip=self.trip, user=self.alice, role=TripRole.EDITOR)
        self.url = reverse("bucketlists:trip_done", args=[self.trip.pk])

    def test_linked_goal_goes_to_its_done_page(self):
        item = BucketListItem.objects.create(user=self.alice, custom_title="Learn to surf", trip=self.trip, status="planning")
        self.assertTrue(item.trip_finished)
        self.assertRedirects(self.client.post(self.url), reverse("bucketlists:item_complete", args=[item.pk]))
        page = self.client.get(reverse("bucketlists:dashboard"))
        self.assertContains(page, "Trip over: tick it off")
        self.assertEqual([i.title for i in self.client.get(reverse("bucketlists:dates")).context["past"]], ["Learn to surf"])

    def test_unlinked_trip_creates_a_goal(self):
        response = self.client.post(self.url)
        item = BucketListItem.objects.get(user=self.alice)
        self.assertRedirects(response, reverse("bucketlists:item_complete", args=[item.pk]))
        self.assertEqual((item.title, item.trip, item.target_date), ("Surf week", self.trip, self.trip.start_date))
        self.client.post(self.url)  # second click: no second goal
        self.assertEqual(BucketListItem.objects.filter(user=self.alice).count(), 1)

    def test_trip_must_be_visible(self):
        self.client.force_login(self.bob)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 405)


class SeveralGoalsOneTripTests(BucketFixture):
    """A trip can carry several bucket-list goals."""

    def setUp(self):
        super().setUp()
        start = date.today() + timedelta(days=30)
        self.trip = Trip.objects.create(name="Testville weekend", start_date=start, end_date=start + timedelta(days=3))
        TripGrant.objects.create(trip=self.trip, user=self.alice, role=TripRole.VIEWER)  # a traveller, not the planner
        self.concert = BucketListItem.objects.create(user=self.alice, custom_title="See a concert", target_date=start)
        self.museum = BucketListItem.objects.create(user=self.alice, custom_title="Visit the museum")

    def test_plan_a_trip_offers_existing_trips(self):
        page = self.client.get(reverse("bucketlists:plan_trip", args=[self.concert.pk]))
        self.assertContains(page, "Testville weekend")
        self.assertContains(page, "Same dates")
        response = self.client.post(reverse("bucketlists:add_to_trip", args=[self.concert.pk]), {"trip": self.trip.pk})
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk]))
        self.concert.refresh_from_db()
        self.assertEqual((self.concert.trip, self.concert.status), (self.trip, "planning"))

    def test_add_several_from_the_trip_side(self):
        url = reverse("bucketlists:trip_goals", args=[self.trip.pk])
        self.assertContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), url)
        page = self.client.get(url)
        self.assertEqual([i.title for i in page.context["available"]], ["See a concert", "Visit the museum"])  # same dates first
        self.client.post(url, {"items": [self.concert.pk, self.museum.pk]})
        self.assertEqual(set(self.trip.bucket_list_items.values_list("custom_title", flat=True)), {"See a concert", "Visit the museum"})
        self.assertEqual([i.title for i in self.client.get(url).context["on_trip"]], ["See a concert", "Visit the museum"])

    def test_remove_and_move(self):
        other = Trip.objects.create(name="Other", start_date=date.today() + timedelta(days=90), end_date=date.today() + timedelta(days=95))
        TripGrant.objects.create(trip=other, user=self.alice, role=TripRole.EDITOR)
        self.client.post(reverse("bucketlists:add_to_trip", args=[self.museum.pk]), {"trip": other.pk})
        self.client.post(reverse("bucketlists:trip_goals", args=[self.trip.pk]), {"items": [self.museum.pk]})  # moves it
        self.museum.refresh_from_db()
        self.assertEqual(self.museum.trip, self.trip)
        self.client.post(reverse("bucketlists:remove_from_trip", args=[self.museum.pk]))
        self.museum.refresh_from_db()
        self.assertIsNone(self.museum.trip)
        self.assertTrue(Trip.objects.filter(pk=self.trip.pk).exists())  # the trip is untouched

    def test_only_your_goals_and_visible_trips(self):
        hidden = Trip.objects.create(name="Secret", start_date=date.today(), end_date=date.today() + timedelta(days=1))
        self.assertEqual(self.client.post(reverse("bucketlists:add_to_trip", args=[self.concert.pk]), {"trip": hidden.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse("bucketlists:trip_goals", args=[hidden.pk])).status_code, 404)
        bobs = BucketListItem.objects.create(user=self.bob, custom_title="Bob's goal")
        self.client.post(reverse("bucketlists:trip_goals", args=[self.trip.pk]), {"items": [bobs.pk]})
        bobs.refresh_from_db()
        self.assertIsNone(bobs.trip)


class AdventuresTests(BucketFixture):
    """Photos when ticking a goal off, and the My adventures timeline."""

    def setUp(self):
        super().setUp()
        import tempfile
        self.media_root = tempfile.mkdtemp(prefix="sbl-test-adventures-")
        self.settings_override = self.settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.item = BucketListItem.objects.create(user=self.alice, custom_title="See the northern lights", is_public=True)

    def tearDown(self):
        import shutil
        self.settings_override.disable()
        shutil.rmtree(self.media_root, ignore_errors=True)
        super().tearDown()

    def photo(self, name):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (30, 20), "green").save(buf, format="JPEG")
        return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")

    def complete(self, **extra):
        data = {"completed_date": "2026-09-01", "user_rating": "5", "completion_notes": "Magical"}
        data.update(extra)
        return self.client.post(reverse("bucketlists:item_complete", args=[self.item.pk]), data)

    def test_photos_attach_to_the_goal_and_show_in_adventures(self):
        response = self.complete(photos=[self.photo("a.jpg"), self.photo("b.jpg")])
        self.assertRedirects(response, reverse("bucketlists:adventures"))
        photos = list(self.item.photos())
        self.assertEqual(len(photos), 2)
        self.assertEqual((photos[0].uploaded_by, photos[0].content_object), (self.alice, self.item))
        page = self.client.get(reverse("bucketlists:adventures"))
        self.assertContains(page, "See the northern lights")
        self.assertContains(page, photos[0].file.url)
        self.assertContains(page, "Magical")
        # more photos later, from the same page
        self.complete(photos=[self.photo("c.jpg")])
        self.assertEqual(self.item.photos().count(), 3)

    def test_not_an_image_is_refused(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        response = self.complete(photos=[SimpleUploadedFile("x.jpg", b"nope", content_type="image/jpeg")])
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertNotEqual(self.item.status, "completed")

    def test_adventures_is_private_and_lists_unlinked_finished_trips(self):
        trip = Trip.objects.create(name="Iceland week", start_date=date.today() - timedelta(days=30),
                                   end_date=date.today() - timedelta(days=23))
        TripGrant.objects.create(trip=trip, user=self.alice, role=TripRole.VIEWER)
        self.complete()
        page = self.client.get(reverse("bucketlists:adventures"))
        self.assertContains(page, "Iceland week")
        self.assertContains(page, reverse("bucketlists:trip_done", args=[trip.pk]))
        self.client.force_login(self.bob)
        page = self.client.get(reverse("bucketlists:adventures"))
        self.assertNotContains(page, "See the northern lights")
        self.assertNotContains(page, "Iceland week")

    def test_public_list_shows_first_photo(self):
        self.alice.profile_visibility = "public"
        self.alice.save()
        self.complete(photos=[self.photo("first.jpg")])
        first = self.item.photos().first()
        self.client.logout()
        self.assertContains(self.client.get(reverse("bucketlists:public_list", args=["alice"])), first.file.url)


class TripCitiesFromGoalsTests(BucketFixture):
    def test_plan_a_trip_takes_the_goals_cities(self):
        item = BucketListItem.objects.create(user=self.alice, city=self.city, target_date=date.today() + timedelta(days=60))
        self.client.post(reverse("bucketlists:plan_trip", args=[item.pk]), {
            "name": "Testville", "start_date": str(date.today() + timedelta(days=60)),
            "end_date": str(date.today() + timedelta(days=63))})
        self.assertEqual(list(Trip.objects.get(name="Testville").cities.all()), [self.city])

    def test_a_viewer_attaching_a_goal_does_not_change_the_trip(self):
        trip = Trip.objects.create(name="Family", start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=9))
        TripGrant.objects.create(trip=trip, user=self.alice, role=TripRole.VIEWER)
        item = BucketListItem.objects.create(user=self.alice, city=self.city)
        self.client.post(reverse("bucketlists:add_to_trip", args=[item.pk]), {"trip": trip.pk})
        item.refresh_from_db()
        self.assertEqual((item.trip, trip.cities.count()), (trip, 0))


class BadgeTests(BucketFixture):
    """Badges are earned once, notified once, and shown with progress."""

    def test_first_goal_and_first_adventure(self):
        from apps.bucketlists.models import BucketListMilestone
        from apps.notifications.models import Notification
        item = BucketListItem.objects.create(user=self.alice, custom_title="Surf")
        self.assertEqual(list(BucketListMilestone.objects.filter(user=self.alice).values_list("code", flat=True)), ["first_goal"])
        item.complete()
        codes = set(BucketListMilestone.objects.filter(user=self.alice).values_list("code", flat=True))
        self.assertEqual(codes, {"first_goal", "first_done"})
        item.save()  # nothing new: no duplicate rows or notifications
        self.assertEqual(BucketListMilestone.objects.filter(user=self.alice).count(), 2)
        self.assertEqual(Notification.objects.filter(user=self.alice, notification_type__name="badge_earned").count(), 2)

    def test_countries_and_events(self):
        from apps.bucketlists.badges import award_badges, progress
        other = Country.objects.create(name="Otherland", slug="otherland", iso_code="OL", iso3_code="OTL", continent="Asia")
        far = City.objects.create(name="Faraway", slug="faraway", country=other, latitude=1, longitude=2,
                                  approval_status=ApprovalStatus.APPROVED)
        BucketListItem.objects.create(user=self.alice, city=self.city).complete()
        BucketListItem.objects.create(user=self.alice, city=far).complete()
        BucketListItem.objects.create(user=self.alice, event=self.event).complete()
        rows = {b.code: (earned, current, target) for b, earned, current, target in progress(self.alice)}
        self.assertEqual(rows["three_countries"][1:], (2, 3))
        self.assertIsNone(rows["three_countries"][0])
        self.assertIsNotNone(rows["first_event"][0])
        self.assertEqual(award_badges(self.alice), [])  # already up to date

    def test_backfill_command_is_silent(self):
        from io import StringIO
        from django.core.management import call_command
        from apps.bucketlists.models import BucketListMilestone
        from apps.notifications.models import Notification
        BucketListItem.objects.create(user=self.alice, custom_title="Surf")
        BucketListMilestone.objects.all().delete()
        Notification.objects.all().delete()
        out = StringIO()
        call_command("award_badges", stdout=out)
        self.assertIn("alice: Dreamer", out.getvalue())
        self.assertEqual(Notification.objects.count(), 0)

    def test_shown_on_dashboard_adventures_and_public_page(self):
        BucketListItem.objects.create(user=self.alice, custom_title="Surf", is_public=True).complete()
        self.assertContains(self.client.get(reverse("pages:dashboard")), "First adventure")
        page = self.client.get(reverse("bucketlists:adventures"))
        self.assertContains(page, "First adventure")
        self.assertContains(page, "1 / 5")  # Adventurer: one of five so far
        self.alice.profile_visibility = "public"
        self.alice.save()
        self.client.logout()
        public = self.client.get(reverse("bucketlists:public_list", args=["alice"]))
        self.assertContains(public, "First adventure")
        self.assertNotContains(public, "Adventurer")  # unearned badges stay private


class VisitorCountTests(BucketFixture):
    """visitor_count = members who ticked off a goal there or finished a trip there."""

    def setUp(self):
        super().setUp()
        self.region = Region.objects.create(country=self.city.country, name="North", slug="north")
        self.city.region = self.region
        self.city.save()

    def counts(self):
        from django.db import connection
        for model, obj in ((City, self.city), (POI, self.poi), (Region, self.region), (Country, self.city.country)):
            obj.refresh_from_db()
        return (self.city.visitor_count, self.poi.visitor_count, self.region.visitor_count, self.city.country.visitor_count)

    def commit(self):
        """Signals recount on transaction commit; TestCase never commits, so run the hooks."""
        from django.db import connection
        callbacks = list(connection.run_on_commit)
        connection.run_on_commit.clear()
        for _, func, *_ in callbacks:
            func()

    def test_completed_goals_count_once_per_member(self):
        BucketListItem.objects.create(user=self.alice, city=self.city).complete()
        poi_goal = BucketListItem.objects.create(user=self.alice)
        poi_goal.pois.add(self.poi)
        poi_goal.complete()
        BucketListItem.objects.create(user=self.bob, city=self.city)  # not done: doesn't count
        self.commit()
        self.assertEqual(self.counts(), (1, 1, 1, 1))
        BucketListItem.objects.create(user=self.bob, event=self.event).complete()  # event in the city
        self.commit()
        self.assertEqual(self.counts()[0], 2)

    def test_uncompleting_or_deleting_lowers_it(self):
        goal = BucketListItem.objects.create(user=self.alice, city=self.city)
        goal.complete()
        self.commit()
        self.assertEqual(self.counts()[0], 1)
        goal.status = "planning"
        goal.save()
        self.commit()
        self.assertEqual(self.counts()[0], 0)

    def test_finished_trips_count_their_travellers_not_other_grant_holders(self):
        from apps.trips.models import Traveler
        trip = Trip.objects.create(name="Done", start_date=date.today() - timedelta(days=10), end_date=date.today() - timedelta(days=3))
        traveller = Traveler.objects.get(user=self.alice)  # every account is a traveller
        trip.travelers.add(traveller)
        TripGrant.objects.create(trip=trip, user=self.bob, role=TripRole.VIEWER)  # can see it, didn't go
        trip.cities.add(self.city)
        self.commit()
        self.assertEqual(self.counts()[0], 1)
        future = Trip.objects.create(name="Soon", start_date=date.today() + timedelta(days=3), end_date=date.today() + timedelta(days=5))
        future.travelers.add(Traveler.objects.get(user=self.bob))
        future.cities.add(self.city)
        self.commit()
        self.assertEqual(self.counts()[0], 1)

    def test_command_recounts_from_scratch(self):
        from io import StringIO
        from django.core.management import call_command
        BucketListItem.objects.create(user=self.alice, city=self.city).complete()
        City.objects.update(visitor_count=0)
        call_command("recount_visitors", stdout=StringIO())
        self.assertEqual(self.counts()[0], 1)

    def test_page_shows_it_only_when_nonzero(self):
        url = reverse("locations:city_detail", args=[self.city.slug])
        self.assertNotContains(self.client.get(url), "Members who&#x27;ve been")
        City.objects.filter(pk=self.city.pk).update(visitor_count=4)
        self.assertContains(self.client.get(url), "Members who've been")


class ShareReviewTests(BucketFixture):
    """Mark done can share the rating and notes as a public review (apps.reviews)."""

    def complete(self, item, **extra):
        data = {"completed_date": "2026-09-01", "user_rating": "4", "completion_notes": "Worth the climb"}
        data.update(extra)
        return self.client.post(reverse("bucketlists:item_complete", args=[item.pk]), data)

    def test_sharing_creates_a_been_there_review_and_updates_it(self):
        from apps.reviews.models import Review
        item = BucketListItem.objects.create(user=self.alice, activity=self.activity)
        self.assertContains(self.client.get(reverse("bucketlists:item_complete", args=[item.pk])), "Share as a public review")
        self.complete(item, share_review="on")
        review = Review.objects.get(user=self.alice, activity=self.activity)
        self.assertEqual((review.rating, review.comment, review.is_verified_visit, review.visit_date),
                         (4, "Worth the climb", True, date(2026, 9, 1)))
        self.complete(item, share_review="on", user_rating="5")
        self.assertEqual(Review.objects.get(pk=review.pk).rating, 5)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.review_count, 1)

    def test_not_shared_unless_ticked(self):
        from apps.reviews.models import Review
        item = BucketListItem.objects.create(user=self.alice, city=self.city)
        self.complete(item)
        self.assertFalse(Review.objects.exists())

    def test_sharing_needs_a_rating(self):
        from apps.reviews.models import Review
        item = BucketListItem.objects.create(user=self.alice, city=self.city)
        response = self.complete(item, share_review="on", user_rating="")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Review.objects.exists())

    def test_custom_goals_are_not_reviewable(self):
        item = BucketListItem.objects.create(user=self.alice, custom_title="Learn to surf")
        self.assertNotContains(self.client.get(reverse("bucketlists:item_complete", args=[item.pk])), "Share as a public review")

    def test_review_from_the_page_is_been_there_after_ticking_off(self):
        from apps.reviews.models import Review
        item = BucketListItem.objects.create(user=self.alice, custom_title="Bridge")
        item.pois.add(self.poi)
        item.complete(date(2026, 9, 1))
        self.client.post(reverse("reviews:write", args=["poi", self.poi.slug]), {"rating": 5, "comment": "Grand"})
        self.assertTrue(Review.objects.get(user=self.alice).is_verified_visit)
        self.client.force_login(self.bob)
        self.client.post(reverse("reviews:write", args=["poi", self.poi.slug]), {"rating": 2, "comment": "Meh"})
        self.assertFalse(Review.objects.get(user=self.bob).is_verified_visit)


class TripMapPlacesTests(BucketFixture):
    """The trip map's "Places of interest" layer: your own goals' places on that trip."""

    def setUp(self):
        super().setUp()
        self.trip = Trip.objects.create(name="Testland week", start_date=date(2027, 5, 1), end_date=date(2027, 5, 7),
                                        created_by=self.alice)
        for user in (self.alice, self.bob):
            TripGrant.objects.create(trip=self.trip, user=user, role=TripRole.VIEWER)
        self.hall = POI.objects.create(name="Music Hall", slug="music-hall", city=self.city, latitude=3, longitude=4,
                                       approval_status=ApprovalStatus.APPROVED)
        self.activity.venue = self.hall
        self.activity.save()
        poi_goal = BucketListItem.objects.create(user=self.alice, custom_title="Bridges", trip=self.trip)
        poi_goal.pois.add(self.poi)
        BucketListItem.objects.create(user=self.alice, activity=self.activity, trip=self.trip)
        hidden = POI.objects.create(name="Unapproved", slug="unapproved", city=self.city, latitude=5, longitude=6,
                                    approval_status=ApprovalStatus.PENDING)
        BucketListItem.objects.create(user=self.alice, custom_title="Secret", trip=self.trip).pois.add(hidden)
        BucketListItem.objects.create(user=self.bob, custom_title="Bob's", trip=self.trip).pois.add(self.hall)
        self.url = reverse("bucketlists:trip_map_places", args=[self.trip.pk])

    def test_own_goals_places_only(self):
        data = self.client.get(self.url).json()
        names = [(f["properties"]["name"], f["properties"]["layer"], f["properties"]["marker"]) for f in data["features"]]
        self.assertEqual(names, [("Music Hall", "pois", "poi"), ("Old Bridge", "pois", "poi")])
        self.assertIn("for Ridge Walk", data["features"][0]["properties"]["subtitle"])
        self.client.force_login(self.bob)
        self.assertEqual([f["properties"]["name"] for f in self.client.get(self.url).json()["features"]], ["Music Hall"])

    def test_no_grant_is_404(self):
        stranger = User.objects.create_user("carol", "carol@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)
