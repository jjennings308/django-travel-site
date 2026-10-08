"""activities.0010 links free-text suggested_location to catalogue places."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("activities", "0009_activity_location_recurrence")]
AFTER = [("activities", "0010_link_suggested_locations")]


class LinkLocationsMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        """Migrate activities to ``targets``; every other app stays at its latest migration."""
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        pinned = dict(targets)
        nodes = [(app, pinned.get(app, name)) for app, name in executor.loader.graph.leaf_nodes()]
        executor.migrate(nodes)
        executor.loader.build_graph()
        return executor.loader.project_state(nodes).apps

    def tearDown(self):
        self.migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_links_city_or_country(self):
        apps = self.migrate(BEFORE)
        Activity = apps.get_model("activities", "Activity")
        Category = apps.get_model("activities", "ActivityCategory")
        User = apps.get_model("accounts", "User")
        Country = apps.get_model("locations", "Country")
        Region = apps.get_model("locations", "Region")
        City = apps.get_model("locations", "City")
        user = User.objects.create(username="u", email="u@example.com")
        cat, _ = Category.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        germany = Country.objects.create(name="Germany", slug="germany", iso_code="DE", iso3_code="DEU", continent="Europe")
        bavaria = Region.objects.create(country=germany, name="Bavaria", slug="bavaria")
        munich = City.objects.create(name="Munich", slug="munich", country=germany, region=bavaria, latitude=48, longitude=11)
        make = lambda name, where: Activity.objects.create(category=cat, name=name, slug=name.lower(), description="d",
                                                           created_by=user, suggested_location=where)
        okto, berlin, sphere = make("Okto", "Munich, Germany"), make("Wall", "Berlin, Germany"), make("Sphere", "Vegas Sphere")

        apps = self.migrate(AFTER)
        Activity = apps.get_model("activities", "Activity")
        okto, berlin, sphere = (Activity.objects.get(pk=a.pk) for a in (okto, berlin, sphere))
        self.assertEqual((okto.city_id, okto.region_id, okto.country_id, okto.suggested_location), (munich.pk, bavaria.pk, germany.pk, ""))
        self.assertEqual((berlin.city_id, berlin.country_id, berlin.suggested_location), (None, germany.pk, "Berlin, Germany"))
        self.assertEqual((sphere.country_id, sphere.suggested_location), (None, "Vegas Sphere"))

        apps = self.migrate(BEFORE)
        self.assertEqual(apps.get_model("activities", "Activity").objects.get(pk=okto.pk).suggested_location, "Munich, Germany")
