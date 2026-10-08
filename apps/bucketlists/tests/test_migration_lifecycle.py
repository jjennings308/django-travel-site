"""bucketlists.0003–0005 on old-style data: each item's single POI moves into
`pois`, and an event-only item whose event is a date of an activity becomes an
activity item carrying that event."""
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("bucketlists", "0002_poi_categories_private_default")]
AFTER = [("bucketlists", "0005_lifecycle_drop_poi")]


class LifecycleMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        """Migrate bucketlists to ``targets``; every other app stays at its latest migration."""
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_pois_and_event_items_carried_across(self):
        apps = self.migrate(BEFORE)
        Item = apps.get_model("bucketlists", "BucketListItem")
        User = apps.get_model("accounts", "User")
        Country = apps.get_model("locations", "Country")
        City = apps.get_model("locations", "City")
        POI = apps.get_model("locations", "POI")
        ActivityCategory = apps.get_model("activities", "ActivityCategory")
        Activity = apps.get_model("activities", "Activity")
        Event = apps.get_model("events", "Event")

        user = User.objects.create(username="u", email="u@example.com")
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe")
        city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=2)
        poi = POI.objects.create(name="Old Bridge", slug="old-bridge", city=city, latitude=1, longitude=2)
        festival, _ = ActivityCategory.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        okto = Activity.objects.create(category=festival, name="Oktoberfest", slug="okto", description="d", created_by=user)
        dated = Event.objects.create(name="Okto 2027", slug="okto-2027", category=festival, related_activity=okto,
                                     description="d", city=city, start_date=date(2027, 9, 18))
        loose = Event.objects.create(name="Gig", slug="gig", category=festival, description="d", city=city,
                                     start_date=date(2027, 1, 1))
        poi_item = Item.objects.create(user=user, poi=poi)
        dated_item = Item.objects.create(user=user, event=dated)
        loose_item = Item.objects.create(user=user, event=loose)

        apps = self.migrate(AFTER)
        Item = apps.get_model("bucketlists", "BucketListItem")
        self.assertEqual(list(Item.objects.get(pk=poi_item.pk).pois.values_list("pk", flat=True)), [poi.pk])
        dated_item = Item.objects.get(pk=dated_item.pk)
        self.assertEqual((dated_item.activity_id, dated_item.event_id), (okto.pk, dated.pk))
        loose_item = Item.objects.get(pk=loose_item.pk)
        self.assertEqual((loose_item.activity_id, loose_item.event_id), (None, loose.pk))

        apps = self.migrate(BEFORE)  # and back
        Item = apps.get_model("bucketlists", "BucketListItem")
        self.assertEqual(Item.objects.get(pk=poi_item.pk).poi_id, poi.pk)
        self.assertEqual(Item.objects.get(pk=dated_item.pk).activity_id, None)
