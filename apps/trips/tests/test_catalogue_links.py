"""Meals and sections linked to the catalogue, and "On trips · N" (site roadmap R18)."""
from datetime import date, time
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country
from apps.trips import catalogue_counts, catalogue_links
from apps.trips.forms import MealForm, SectionForm
from apps.trips.models import Day, Meal, Section, TidyDismissal, Trip, TripActivity, TripGrant, TripRole

User = get_user_model()
APPROVED = {"approval_status": ApprovalStatus.APPROVED}


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="London", start_date=date(2027, 5, 1), end_date=date(2027, 5, 3),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 5, 1))
        uk = Country.objects.create(name="United Kingdom", slug="uk", iso_code="GB", iso3_code="GBR",
                                    continent="Europe", **APPROVED)
        fr = Country.objects.create(name="France", slug="fr", iso_code="FR", iso3_code="FRA", continent="Europe",
                                    **APPROVED)
        self.london = City.objects.create(name="London", slug="london", country=uk, latitude=51.5, longitude=0,
                                          **APPROVED)
        self.paris = City.objects.create(name="Paris", slug="paris", country=fr, latitude=48.8, longitude=2.3,
                                         **APPROVED)
        self.market = POI.objects.create(name="Borough Market", slug="borough-market", city=self.london,
                                         latitude=51.5, longitude=0, poi_type_id="food", **APPROVED)
        self.tate = POI.objects.create(name="Tate Modern", slug="tate-modern", city=self.london, latitude=51.5,
                                       longitude=0, poi_type_id="museum", **APPROVED)
        self.louvre = POI.objects.create(name="Louvre", slug="louvre", city=self.paris, latitude=48.8,
                                         longitude=2.3, **APPROVED)
        self.pending = POI.objects.create(name="New Cafe", slug="new-cafe", city=self.london, latitude=51.5,
                                          longitude=0)
        category = ActivityCategory.objects.create(name="Walks", slug="walks")
        self.walk = Activity.objects.create(name="Thames walk", slug="thames-walk", category=category,
                                            description="x", city=self.london, visibility="public", **APPROVED)
        self.paris_walk = Activity.objects.create(name="Seine walk", slug="seine-walk", category=category,
                                                  description="x", city=self.paris, visibility="public",
                                                  **APPROVED)
        self.trip.cities.add(self.london)


class FormTests(Fixture):
    def test_meal_places_are_the_trips_cities_approved_food_first(self):
        form = MealForm(trip=self.trip)
        self.assertEqual(list(form.fields["poi"].queryset), [self.market, self.tate])

    def test_a_place_elsewhere_is_refused(self):
        data = {"name": "Lunch", "meal_type": "lunch", "poi": self.louvre.pk}
        form = MealForm(data, instance=Meal(day=self.day))
        self.assertFalse(form.is_valid())
        self.assertIn("poi", form.errors)

    def test_section_place_and_activity(self):
        section = Section(day=self.day, section_type="free_text")
        form = SectionForm({"title": "Walk", "poi": self.tate.pk, "activity": self.walk.pk}, instance=section)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn(self.paris_walk, form.fields["activity"].queryset)
        refused = SectionForm({"title": "Walk", "activity": self.paris_walk.pk}, instance=section)
        self.assertFalse(refused.is_valid())

    def test_no_cities_no_choices(self):
        self.trip.cities.clear()
        self.assertFalse(MealForm(trip=self.trip).fields["poi"].queryset.exists())


class SuggestionTests(Fixture):
    def page(self):
        self.client.force_login(self.editor)
        return self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.day.pk]))

    def test_exact_name_is_suggested_and_linked_on_request(self):
        meal = Meal.objects.create(day=self.day, name="borough  market!", meal_type="lunch")
        self.assertContains(self.page(), "Looks like the catalogue place")
        meal.refresh_from_db()
        self.assertIsNone(meal.poi_id)  # never automatic
        url = reverse("trips:catalogue_link", args=[self.trip.pk, self.day.pk, "meal", meal.pk])
        self.client.post(url, {"target_kind": "poi", "target": self.market.pk})
        meal.refresh_from_db()
        self.assertEqual(meal.poi, self.market)
        self.assertNotContains(self.page(), "Looks like")

    def test_section_title_matches_an_activity(self):
        Section.objects.create(day=self.day, section_type="free_text", title="Thames Walk")
        self.assertContains(self.page(), "Looks like the catalogue activity")

    def test_partial_names_other_cities_and_ambiguous_names_suggest_nothing(self):
        Meal.objects.create(day=self.day, name="Lunch at Borough Market", meal_type="lunch")
        Meal.objects.create(day=self.day, name="Louvre", meal_type="lunch")
        POI.objects.create(name="Tate Modern", slug="tate-modern-2", city=self.london, latitude=1, longitude=1,
                           **APPROVED)
        Meal.objects.create(day=self.day, name="Tate Modern", meal_type="lunch")
        self.assertNotContains(self.page(), "Looks like")

    def test_not_this_one_hides_it(self):
        meal = Meal.objects.create(day=self.day, name="Borough Market", meal_type="lunch")
        url = reverse("trips:catalogue_link", args=[self.trip.pk, self.day.pk, "meal", meal.pk])
        self.client.force_login(self.editor)
        self.client.post(url, {"target_kind": "poi", "target": self.market.pk, "dismiss": "1"})
        self.assertTrue(TidyDismissal.objects.filter(trip=self.trip, key__startswith="catalogue:").exists())
        self.assertNotContains(self.page(), "Looks like")
        meal.refresh_from_db()
        self.assertIsNone(meal.poi_id)

    def test_target_outside_the_trip_is_refused_and_viewers_cannot_link(self):
        meal = Meal.objects.create(day=self.day, name="Louvre", meal_type="lunch")
        url = reverse("trips:catalogue_link", args=[self.trip.pk, self.day.pk, "meal", meal.pk])
        self.client.force_login(self.editor)
        self.client.post(url, {"target_kind": "poi", "target": self.louvre.pk})
        self.client.post(url, {"target_kind": "activity", "target": self.walk.pk})  # meals take places only
        meal.refresh_from_db()
        self.assertIsNone(meal.poi_id)
        self.client.force_login(self.viewer)
        response = self.client.post(url, {"target_kind": "poi", "target": self.market.pk})
        self.assertEqual(response.status_code, 403)


class DisplayTests(Fixture):
    def test_trip_page_links_the_catalogue_items(self):
        Meal.objects.create(day=self.day, name="Lunch", meal_type="lunch", poi=self.market,
                            reserved_time=time(12, 0))
        Meal.objects.create(day=self.day, name="Snack", meal_type="snack", poi=self.tate)  # a food idea
        Section.objects.create(day=self.day, section_type="free_text", title="Afternoon", activity=self.walk,
                               content={"paragraphs": ["x"]})
        self.client.force_login(self.viewer)
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(page, reverse("locations:poi_detail", args=[self.market.slug]))
        self.assertContains(page, reverse("locations:poi_detail", args=[self.tate.slug]))
        self.assertContains(page, reverse("activities:activity_detail", args=[self.walk.slug]))


class CountTests(Fixture):
    def other_trip(self, name="Second"):
        trip = Trip.objects.create(name=name, start_date=date(2027, 6, 1), end_date=date(2027, 6, 2))
        return trip, Day.objects.create(trip=trip, day_number=1, date=date(2027, 6, 1))

    def test_each_live_trip_counts_once(self):
        Meal.objects.create(day=self.day, name="Lunch", meal_type="lunch", poi=self.market)
        Section.objects.create(day=self.day, section_type="free_text", poi=self.market, activity=self.walk)
        TripActivity.objects.create(trip=self.trip, day=self.day, title="Tour", poi=self.market)
        catalogue_counts.recount()
        self.market.refresh_from_db()
        self.assertEqual(self.market.trip_count, 1)
        self.assertEqual(self.market.shown_trip_count, 0)  # one trip is never shown

        second, day = self.other_trip()
        TripActivity.objects.create(trip=second, day=day, title="Food tour", poi=self.market)
        Section.objects.create(day=day, section_type="free_text", activity=self.walk)
        deleted, gone_day = self.other_trip("Deleted")
        Meal.objects.create(day=gone_day, name="Lunch", meal_type="lunch", poi=self.market)
        deleted.soft_delete()
        out = StringIO()
        call_command("recount_visitors", stdout=out)
        self.assertIn("trip count(s) changed", out.getvalue())
        self.market.refresh_from_db()
        self.walk.refresh_from_db()
        self.assertEqual((self.market.trip_count, self.market.shown_trip_count), (2, 2))
        self.assertEqual(self.walk.trip_count, 2)

        Meal.objects.all().delete()
        Section.objects.all().delete()
        TripActivity.objects.all().delete()
        catalogue_counts.recount()
        self.market.refresh_from_db()
        self.walk.refresh_from_db()
        self.assertEqual((self.market.trip_count, self.walk.trip_count), (0, 0))

    def test_pages_show_the_number_only_from_two_and_never_the_trips(self):
        anyone = User.objects.create_user("an", "an@example.com", "pw-1234-abcd")
        self.client.force_login(anyone)
        POI.objects.filter(pk=self.market.pk).update(trip_count=1)
        Activity.objects.filter(pk=self.walk.pk).update(trip_count=1)
        place = reverse("locations:poi_detail", args=[self.market.slug])
        activity = reverse("activities:activity_detail", args=[self.walk.slug])
        self.assertNotContains(self.client.get(place), "On trips")
        self.assertNotContains(self.client.get(activity), "On trips")
        POI.objects.filter(pk=self.market.pk).update(trip_count=2)
        Activity.objects.filter(pk=self.walk.pk).update(trip_count=3)
        page = self.client.get(place)
        self.assertContains(page, "On trips")
        self.assertNotContains(page, self.trip.name + "</")
        self.assertContains(self.client.get(activity), "On trips")


class FoodTypeTests(TestCase):
    def test_food_and_drink_type_is_seeded(self):
        from apps.locations.models import PlaceType
        self.assertEqual(PlaceType.objects.get(code="food").name, "Food & drink")


class ImportMatchTests(Fixture):
    def test_dry_run_lists_exact_matches_and_links_nothing(self):
        parsed_days = [{"day_number": 2, "meals": [{"name": "Borough Market"}, {"name": "Pret"}],
                        "sections": [{"title": "Thames walk", "content": {}},
                                     {"title": "x", "content": {"heading": "Louvre"}}]}]
        matches = catalogue_links.import_matches(parsed_days)
        self.assertEqual(sorted((m[1], m[2]) for m in matches),
                         [("meal", "Borough Market"), ("section", "Louvre"), ("section", "Thames walk")])
        self.assertIn("place Borough Market, London", [m[3] for m in matches])
        self.assertFalse(Meal.objects.exists())
