"""Bucket-list goals and the trip's Ideas shelf (docs/plans/day-first-planning.md, P6): a goal on a trip is
an idea there, whose owner's goal shows on the shelf and counts as their vote; a finished trip offers
"tick it off" only for goals whose idea made it onto the trip; Save for someday adds a goal from an idea
or a considered option."""
from datetime import date, timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse

from apps.bucketlists.models import BucketListItem
from apps.core.testing import RestoringTransactionTestCase
from apps.trips.models import Option, OptionGroup, Trip, TripActivity, TripGrant, TripIdea, TripRole, Vote

from .test_bucketlists import BucketFixture


class TripFixture(BucketFixture):
    def setUp(self):
        super().setUp()
        start = date.today() + timedelta(days=30)
        self.trip = Trip.objects.create(name="Testville weekend", start_date=start, end_date=start + timedelta(days=3),
                                        created_by=self.bob)
        TripGrant.objects.create(trip=self.trip, user=self.bob, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.alice, role=TripRole.COMMENTOR)
        self.day = self.trip.days.create(day_number=1, date=start)

    def add(self, item):
        return self.client.post(reverse("bucketlists:add_to_trip", args=[item.pk]), {"trip": self.trip.pk})


class GoalToIdeaTests(TripFixture):
    def test_a_goal_on_a_trip_is_an_idea_there(self):
        item = BucketListItem.objects.create(user=self.alice, activity=self.activity,
                                             personal_notes="Private reasons")
        self.add(item)
        item.refresh_from_db()
        idea = item.trip_idea
        self.assertEqual((idea.trip, idea.activity, idea.title, idea.notes, idea.added_by),
                         (self.trip, self.activity, "Ridge Walk", "", self.alice))  # never the personal notes
        self.assertEqual(item.trip, self.trip)
        self.assertTrue(Vote.objects.filter(user=self.alice, idea=idea).exists())  # a goal counts as a vote

    def test_goals_about_one_thing_share_an_idea(self):
        mine = BucketListItem.objects.create(user=self.alice, city=self.city)
        self.add(mine)
        bobs = BucketListItem.objects.create(user=self.bob, city=self.city)
        self.client.force_login(self.bob)
        self.add(bobs)
        bobs.refresh_from_db()
        mine.refresh_from_db()
        self.assertEqual(bobs.trip_idea, mine.trip_idea)
        self.assertEqual(mine.trip_idea.votes.count(), 2)
        goals = self.client.get(reverse("bucketlists:idea_goals", args=[self.trip.pk])).json()["ideas"]
        self.assertEqual(goals, {str(mine.trip_idea_id): "Alice's and your goals"})

    def test_whose_goal_shows_on_the_shelf(self):
        item = BucketListItem.objects.create(user=self.alice, custom_title="See a concert")
        self.add(item)
        item.refresh_from_db()
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn(f'data-idea-goal="{item.trip_idea_id}"', page)
        self.assertIn(reverse("bucketlists:idea_goals", args=[self.trip.pk]), page)
        self.client.force_login(self.bob)
        goals = self.client.get(reverse("bucketlists:idea_goals", args=[self.trip.pk])).json()["ideas"]
        self.assertEqual(goals, {str(item.trip_idea_id): "Alice's goal"})
        self.client.force_login(self.bob.__class__.objects.create_user("eve", "eve@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(reverse("bucketlists:idea_goals", args=[self.trip.pk])).status_code, 404)

    def test_plan_a_trip_makes_the_idea(self):
        item = BucketListItem.objects.create(user=self.alice, city=self.city)
        self.client.post(reverse("bucketlists:plan_trip", args=[item.pk]), {
            "name": "Testville", "start_date": str(date.today() + timedelta(days=60)),
            "end_date": str(date.today() + timedelta(days=63))})
        trip = Trip.objects.get(name="Testville")
        self.assertEqual(TripIdea.objects.get(trip=trip).city, self.city)
        self.assertEqual(list(trip.cities.all()), [self.city])  # through the idea

    def test_a_viewer_links_the_goal_only(self):
        TripGrant.objects.filter(trip=self.trip, user=self.alice).update(role=TripRole.VIEWER)
        item = BucketListItem.objects.create(user=self.alice, custom_title="Quiet goal")
        self.add(item)
        item.refresh_from_db()
        self.assertEqual((item.trip, item.trip_idea), (self.trip, None))
        self.assertFalse(TripIdea.objects.exists())

    def test_removing_the_goal_keeps_the_idea(self):
        item = BucketListItem.objects.create(user=self.alice, custom_title="See a concert")
        self.add(item)
        self.client.post(reverse("bucketlists:remove_from_trip", args=[item.pk]))
        item.refresh_from_db()
        self.assertEqual((item.trip, item.trip_idea), (None, None))
        self.assertTrue(TripIdea.objects.filter(trip=self.trip, title="See a concert").exists())

    def test_the_trip_follows_the_idea(self):
        other = Trip.objects.create(name="Other", start_date=self.trip.start_date, end_date=self.trip.end_date)
        idea = TripIdea.objects.create(trip=other, title="X")
        item = BucketListItem.objects.create(user=self.alice, custom_title="X", trip=self.trip)
        item.trip_idea = idea
        item.save(update_fields=["trip_idea"])
        item.refresh_from_db()
        self.assertEqual(item.trip, other)


class DoneTests(TripFixture):
    def setUp(self):
        super().setUp()
        self.trip.start_date, self.trip.end_date = date.today() - timedelta(days=10), date.today() - timedelta(days=3)
        self.trip.save()
        self.url = reverse("bucketlists:trip_done", args=[self.trip.pk])

    def goal(self, title):
        item = BucketListItem.objects.create(user=self.alice, custom_title=title, status="planning")
        self.add(item)
        item.refresh_from_db()
        return item

    def test_only_goals_whose_idea_made_it_onto_the_trip(self):
        done = self.goal("Ridge walk")
        self.goal("Never got a day")
        considered = self.goal("Not chosen")
        done.trip_idea.place_on(TripActivity.objects.create(trip=self.trip, day=self.day, title="Ridge walk"))
        group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Afternoon")
        chosen, other = Option.objects.create(group=group, title="A"), Option.objects.create(group=group, title="B")
        considered.trip_idea.place_on(other)
        group.pick(chosen)
        self.assertRedirects(self.client.post(self.url), reverse("bucketlists:item_complete", args=[done.pk]))

    def test_none_made_it_so_the_trip_itself(self):
        self.goal("Never got a day")
        self.client.post(self.url)
        self.assertTrue(BucketListItem.objects.filter(user=self.alice, custom_title=self.trip.name).exists())


class SaveForSomedayTests(TripFixture):
    def test_from_an_idea(self):
        idea = TripIdea.objects.create(trip=self.trip, title="Old Bridge at dusk", poi=self.poi, added_by=self.bob)
        url = reverse("bucketlists:save_idea")
        self.client.post(url, {"idea": idea.pk, "next": "/trips/"})
        item = BucketListItem.objects.get(user=self.alice)
        self.assertEqual((list(item.pois.all()), item.status, item.trip), ([self.poi], "wishlist", None))
        response = self.client.post(url, {"idea": idea.pk}, follow=True)
        self.assertContains(response, "already on your bucket list")
        self.assertEqual(BucketListItem.objects.filter(user=self.alice).count(), 1)

    def test_from_a_considered_option(self):
        group = OptionGroup.objects.create(trip=self.trip, day=self.day, prompt="Evening")
        jazz = Option.objects.create(group=group, title="Jazz Night")
        TripActivity.objects.create(trip=self.trip, day=self.day, title="Jazz", event=self.event, option=jazz)
        typed = Option.objects.create(group=group, title="Karaoke")
        group.pick(typed)
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn(f'name="option" value="{jazz.pk}"', page)
        self.client.post(reverse("bucketlists:save_idea"), {"option": jazz.pk})
        self.client.post(reverse("bucketlists:save_idea"), {"option": typed.pk})
        self.assertEqual(sorted(i.title for i in BucketListItem.objects.filter(user=self.alice)),
                         ["Jazz Night", "Karaoke"])
        self.assertEqual(BucketListItem.objects.get(user=self.alice, event=self.event).activity, None)

    def test_only_trips_you_can_see(self):
        hidden = Trip.objects.create(name="Secret", start_date=date.today(), end_date=date.today())
        idea = TripIdea.objects.create(trip=hidden, title="Secret idea")
        self.assertEqual(self.client.post(reverse("bucketlists:save_idea"), {"idea": idea.pk}).status_code, 404)


class GoalsToIdeasMigrationTests(RestoringTransactionTestCase):
    """bucketlists 0008: goals already on a trip get an idea on its shelf, and vote for it."""

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_goals_on_trips_become_ideas(self):
        apps = self.migrate([("bucketlists", "0007_goal_trip_idea")])
        User = apps.get_model("accounts", "User")
        Country = apps.get_model("locations", "Country")
        City = apps.get_model("locations", "City")
        Trip = apps.get_model("trips", "Trip")
        Item = apps.get_model("bucketlists", "BucketListItem")
        alice = User.objects.create(username="alice-m", email="alice-m@example.com")
        bob = User.objects.create(username="bob-m", email="bob-m@example.com")
        country = Country.objects.create(name="Migland", slug="migland", iso_code="MG", iso3_code="MGL", continent="Europe")
        city = City.objects.create(name="Migtown", slug="migtown", country=country, latitude=1, longitude=1)
        trip = Trip.objects.create(name="Mig trip", start_date=date(2027, 1, 1), end_date=date(2027, 1, 3))
        a = Item.objects.create(user=alice, city=city, trip=trip, personal_notes="private")
        b = Item.objects.create(user=bob, city=city, trip=trip)
        c = Item.objects.create(user=alice, custom_title="Learn to ski", trip=trip)
        Item.objects.create(user=alice, custom_title="No trip")
        apps = self.migrate([("bucketlists", "0008_goals_to_ideas")])
        Item = apps.get_model("bucketlists", "BucketListItem")
        TripIdea = apps.get_model("trips", "TripIdea")
        Vote = apps.get_model("trips", "Vote")
        ideas = TripIdea.objects.filter(trip_id=trip.pk)
        self.assertEqual(sorted(ideas.values_list("title", flat=True)), ["Learn to ski", "Migtown"])
        shared = Item.objects.get(pk=a.pk).trip_idea_id
        self.assertEqual(Item.objects.get(pk=b.pk).trip_idea_id, shared)
        self.assertEqual(TripIdea.objects.get(pk=shared).notes, "")
        self.assertEqual(Vote.objects.filter(idea_id=shared).count(), 2)
        self.assertIsNotNone(Item.objects.get(pk=c.pk).trip_idea_id)
        self.assertFalse(Item.objects.filter(custom_title="No trip", trip_idea__isnull=False).exists())
        self.assertTrue(all(i.placed_id is None for i in ideas))  # on the shelf
