"""activities.0008 + events.0005/0006 on real-looking data: event categories are
carried across to the shared activity categories by name, and "Concert" activities
are re-filed (Oktoberfest -> Festival, others -> Music) before Concert is removed."""
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("events", "0004_event_unlisted_location"), ("activities", "0007_alter_activity_specificity_level")]
AFTER = [("events", "0006_shared_categories_swap"), ("activities", "0008_shared_categories")]


class SharedCategoryMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        """Migrate events/activities to ``targets``; every other app stays at its latest
        migration, so the historical models (e.g. accounts.User -> "users") match the DB."""
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_categories_carried_across(self):
        apps = self.migrate(BEFORE)
        EventCategory = apps.get_model("events", "EventCategory")
        Event = apps.get_model("events", "Event")
        ActivityCategory = apps.get_model("activities", "ActivityCategory")
        Activity = apps.get_model("activities", "Activity")
        Country = apps.get_model("locations", "Country")
        City = apps.get_model("locations", "City")

        User = apps.get_model("accounts", "User")
        owner = User.objects.create(username="owner", email="owner@example.com")
        concert, _ = ActivityCategory.objects.get_or_create(name="Concert", defaults={"slug": "concert"})
        Activity.objects.create(category=concert, name="Oktoberfest", slug="oktoberfest", description="d", created_by=owner)
        Activity.objects.create(category=concert, name="See Kenny Chesney", slug="kenny", description="d", created_by=owner)
        country = Country.objects.create(name="Testland", slug="testland", iso_code="TL", iso3_code="TLD", continent="Europe")
        city = City.objects.create(name="Testville", slug="testville", country=country, latitude=1, longitude=2)
        music, _ = EventCategory.objects.get_or_create(name="Music", defaults={"slug": "music"})  # as seeded by events.0003
        odd = EventCategory.objects.create(name="Kite Flying", slug="kite-flying")
        Event.objects.create(name="Gig", slug="gig", category=music, description="d", city=city, start_date=date(2027, 1, 1))
        Event.objects.create(name="Kites", slug="kites", category=odd, description="d", city=city, start_date=date(2027, 1, 2))

        apps = self.migrate(AFTER)
        Event = apps.get_model("events", "Event")
        Activity = apps.get_model("activities", "Activity")
        ActivityCategory = apps.get_model("activities", "ActivityCategory")
        self.assertEqual(Event.objects.get(name="Gig").category.name, "Music")
        self.assertEqual(Event.objects.get(name="Kites").category.name, "Other")  # no shared match
        self.assertEqual(Activity.objects.get(name="Oktoberfest").category.name, "Festival")
        self.assertEqual(Activity.objects.get(name="See Kenny Chesney").category.name, "Music")
        self.assertFalse(ActivityCategory.objects.filter(name="Concert").exists())
        self.assertEqual(ActivityCategory.objects.filter(name__in=["Music", "Festival", "Other"]).count(), 3)
        with connection.cursor() as cursor:
            tables = connection.introspection.table_names(cursor)
        self.assertNotIn("event_categories", tables)
