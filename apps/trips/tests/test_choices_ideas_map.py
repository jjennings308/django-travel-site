"""Typed choices T3 (docs/plans/typed-choices.md): ideas become options of choices their kind fits, undecided
options with a place show on the map, and catalogue notes show under options while deciding."""
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.catalogue_notes.models import CatalogueNote
from apps.locations.models import City, Country, POI
from apps.trips import ideas
from apps.trips.models import (Day, Meal, Option, OptionGroup, TripActivity, Trip, TripGrant, TripIdea, TripRole,
                               Vote)

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=APPROVED)
        self.munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=48.1, longitude=11.6,
                                          approval_status=APPROVED)
        self.trip.cities.add(self.munich)
        self.keller = POI.objects.create(name="Augustiner Keller", slug="augustiner", city=self.munich, latitude=48.14,
                                         longitude=11.55, approval_status=APPROVED, poi_type_id="food")
        self.museum = POI.objects.create(name="Deutsches Museum", slug="museum", city=self.munich, latitude=48.13,
                                         longitude=11.58, approval_status=APPROVED)
        category, _ = ActivityCategory.objects.get_or_create(name="Tours", defaults={"slug": "tours"})
        self.tour = Activity.objects.create(name="Beer tour", slug="beer-tour", category=category, description="d",
                                            city=self.munich, venue=self.keller, visibility="public",
                                            approval_status=APPROVED)
        self.day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18), city=self.munich)

    def choice(self, kind, prompt=None):
        return OptionGroup.objects.create(trip=self.trip, day=self.day, prompt=prompt or f"A {kind}", kind=kind)

    def idea(self, title, **link):
        return TripIdea.objects.create(trip=self.trip, title=title, added_by=self.editor, notes="Worth it", **link)

    def add(self, idea, target):
        self.client.force_login(self.editor)
        return self.client.post(reverse("trips:idea_option", args=[self.trip.pk, idea.pk]), {"target": target})


class IdeaTests(Fixture):
    def test_kinds_that_fit(self):
        food, place, typed = self.idea("Keller", poi=self.keller), self.idea("Museum", poi=self.museum), self.idea("x")
        eat, do, stay, any_ = (self.choice(k) for k in ("eat", "do", "stay", "any"))
        self.assertEqual([g.kind for g in (eat, do, stay, any_) if ideas.fits(food, g)], ["eat", "any"])
        self.assertEqual([g.kind for g in (eat, do, stay, any_) if ideas.fits(place, g)], ["do", "any"])
        self.assertEqual([g.kind for g in (eat, do, stay, any_) if ideas.fits(typed, g)], ["any"])
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        card = html[html.index(f'id="idea-{food.pk}"'):html.index(f'id="idea-{place.pk}"')]
        self.assertIn(f'value="group-{eat.pk}"', card)
        self.assertIn(f'value="group-{any_.pk}"', card)
        self.assertNotIn(f'value="group-{do.pk}"', card)

    def test_into_a_typed_choice_the_link_goes_into_the_option(self):
        eat = self.choice("eat")
        idea = self.idea("Keller", poi=self.keller)
        self.add(idea, f"group-{eat.pk}")
        option = eat.options.get()
        self.assertEqual((option.title, option.poi, option.notes), ("Keller", self.keller, "Worth it"))
        self.assertFalse(Meal.objects.exists() or TripActivity.objects.exists())  # Pick makes the item (T2)
        idea.refresh_from_db()
        self.assertEqual(idea.placed, option)

    def test_each_kinds_field(self):
        cases = (("stay", {"city": self.munich}, "city", self.munich),
                 ("do", {"activity": self.tour}, "activity", self.tour),
                 ("do", {"poi": self.museum}, "poi", self.museum))
        for kind, link, field, expected in cases:
            group = self.choice(kind)
            self.add(self.idea(f"{kind} idea", kind_hint=kind if kind == "stay" else "", **link), f"group-{group.pk}")
            self.assertEqual(getattr(group.options.get(), field), expected, (kind, field))
        travel = self.choice("travel")
        self.add(self.idea("To Munich", kind_hint="travel", city=self.munich), f"group-{travel.pk}")
        self.assertEqual(travel.options.get().to_text, "Munich")

    def test_a_choice_it_doesnt_fit_is_refused(self):
        stay = self.choice("stay")
        response = self.add(self.idea("Museum", poi=self.museum), f"group-{stay.pk}")
        self.assertFalse(stay.options.exists())
        self.assertEqual(response.status_code, 302)

    def test_into_anything_the_item_comes_along_as_before(self):
        any_ = self.choice("any")
        self.add(self.idea("Museum", poi=self.museum), f"group-{any_.pk}")
        self.assertEqual(TripActivity.objects.get().option, any_.options.get())

    def test_a_new_choice_gets_the_ideas_kind(self):
        self.add(self.idea("Keller", poi=self.keller), f"day-{self.day.pk}")
        group = OptionGroup.objects.get()
        self.assertEqual((group.kind, group.options.get().poi), ("eat", self.keller))


class MapTests(Fixture):
    def test_undecided_typed_options_with_a_place(self):
        eat = self.choice("eat", "Dinner")
        keller = Option.objects.create(group=eat, title="Keller", poi=self.keller)
        Vote.objects.create(user=self.editor, option=keller)
        Option.objects.create(group=eat, title="Somewhere typed", place_text="Down the road")
        do = self.choice("do", "Afternoon")
        Option.objects.create(group=do, title="Beer tour", activity=self.tour)
        Option.objects.create(group=self.choice("any"), title="Untyped", poi=self.museum)
        picked = self.choice("eat", "Lunch")
        chosen = Option.objects.create(group=picked, title="Picked one", poi=self.museum)
        picked.pick(chosen)
        self.client.force_login(self.viewer)
        data = self.client.get(reverse("trips:trip_map_data", args=[self.trip.pk])).json()
        pins = {f["properties"]["name"]: f for f in data["features"] if f["properties"].get("layer") == "choices"}
        self.assertEqual(set(pins), {"Keller", "Beer tour"})
        self.assertEqual(pins["Keller"]["geometry"]["coordinates"], [11.55, 48.14])
        self.assertEqual(pins["Beer tour"]["geometry"]["coordinates"], [11.55, 48.14])  # the activity's venue
        self.assertEqual(pins["Keller"]["properties"]["subtitle"], "Day 1 · Dinner: undecided · 👍 1")
        page = self.client.get(reverse("trips:trip_map", args=[self.trip.pk])).content.decode()
        self.assertIn('<input type="checkbox" data-layer="choices">', page)  # off until switched on


class NoteTests(Fixture):
    def note(self, **target):
        return CatalogueNote.objects.create(text="Closed Mondays", tone="warning", approval_status=APPROVED, **target)

    def page(self):
        self.client.force_login(self.editor)
        return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()

    def test_notes_show_folded_under_the_option(self):
        self.note(poi=self.keller)
        eat = self.choice("eat", "Dinner")
        Option.objects.create(group=eat, title="Keller", poi=self.keller)
        Option.objects.create(group=eat, title="Elsewhere", place_text="x")
        html = self.page()
        box = html[html.index(f'id="group-{eat.pk}"'):]
        self.assertIn("ⓘ 1 note from the catalogue", box)
        self.assertEqual(box.count("data-option-notes"), 1)
        self.assertIn("Closed Mondays", box)

    def test_an_activitys_venue_notes_come_through(self):
        self.note(poi=self.keller)
        self.note(activity=self.tour)
        do = self.choice("do")
        Option.objects.create(group=do, title="Tour", activity=self.tour)
        self.assertIn("ⓘ 2 notes from the catalogue", self.page())

    def test_no_extra_query(self):
        """The options' notes come in the trip's one notes query."""
        self.note(poi=self.keller)
        Meal.objects.create(day=self.day, name="Lunch", meal_type="lunch", poi=self.museum)  # notes already load
        url = reverse("trips:trip_detail", args=[self.trip.pk])
        self.client.force_login(self.editor)
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(url)
        before = len(ctx.captured_queries)
        eat = self.choice("eat")
        Option.objects.create(group=eat, title="Keller", poi=self.keller)
        Option.objects.create(group=eat, title="Keller again", poi=self.keller)
        with CaptureQueriesContext(connection) as ctx:
            html = self.client.get(url).content.decode()
        self.assertIn("note from the catalogue", html)
        # The choice adds its own fixed queries (groups, options, travellers, votes); the notes add none.
        with CaptureQueriesContext(connection) as again:
            Option.objects.create(group=eat, title="Third", poi=self.keller)
            self.client.get(url)
        self.assertEqual(len(again.captured_queries) - 1, len(ctx.captured_queries))
