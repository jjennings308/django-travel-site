"""The Ideas shelf (docs/plans/day-first-planning.md, P6): adding, voting, putting ideas on a day or into a
"choose one", coming back to the shelf, "Add to a trip" from the catalogue and the map's Ideas layer."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country, POI
from apps.trips import ideas
from apps.trips.models import (Day, Lodging, Meal, Option, OptionGroup, Section, TransportLeg, Trip, TripActivity,
                               TripChange, TripGrant, TripIdea, TripRole, Vote)

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd", first_name="Ed")
        self.commentor = User.objects.create_user("co", "co@example.com", "pw-1234-abcd", first_name="Cora")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor, home_currency="EUR")
        for user, role in ((self.editor, TripRole.EDITOR), (self.commentor, TripRole.COMMENTOR),
                           (self.viewer, TripRole.VIEWER)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=APPROVED, currency_code="EUR")
        self.munich = City.objects.create(name="Munich", slug="munich", country=de, latitude=48.1, longitude=11.6,
                                          approval_status=APPROVED, timezone="Europe/Berlin")
        self.fussen = City.objects.create(name="Füssen", slug="fussen", country=de, latitude=47.6, longitude=10.7,
                                          approval_status=APPROVED, timezone="Europe/Berlin")
        self.castle = POI.objects.create(name="Neuschwanstein Castle", slug="neuschwanstein", city=self.fussen,
                                         latitude=47.56, longitude=10.75, approval_status=APPROVED)
        self.augustiner = POI.objects.create(name="Augustiner Keller", slug="augustiner", city=self.munich,
                                             latitude=48.14, longitude=11.55, approval_status=APPROVED,
                                             poi_type_id="food")
        category, _ = ActivityCategory.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        self.okto = Activity.objects.create(name="Oktoberfest", slug="oktoberfest", category=category, description="d",
                                            city=self.munich, visibility="public", approval_status=APPROVED)
        self.okto27 = Event.objects.create(name="Oktoberfest 2027", slug="oktoberfest-2027", description="d",
                                           category=category, start_date=date(2027, 9, 18), end_date=date(2027, 10, 3),
                                           city=self.munich, related_activity=self.okto, approval_status=APPROVED)
        self.day1 = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18), city=self.munich)
        self.day2 = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 19), city=self.munich)

    def idea(self, title="Day trip to Salzburg", **extra):
        return TripIdea.objects.create(trip=self.trip, title=title, added_by=self.commentor, **extra)

    def page(self, user=None):
        self.client.force_login(user or self.editor)
        return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()

    def shelf(self, html):
        start = html.index('id="ideas"')
        return html[start:html.index("</details>", start)]

    def url(self, name, idea):
        return reverse(f"trips:{name}", args=[self.trip.pk, idea.pk])


class ShelfTests(Fixture):
    def test_commentors_add_ideas_viewers_cannot(self):
        add = reverse("trips:idea_add", args=[self.trip.pk])
        self.client.force_login(self.commentor)
        response = self.client.post(add, {"title": "Beer garden", "kind_hint": "eat"})
        idea = TripIdea.objects.get()
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk]) + f"#idea-{idea.pk}",
                             fetch_redirect_response=False)
        self.assertEqual((idea.added_by, idea.kind), (self.commentor, "eat"))
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(add, {"title": "Nope"}).status_code, 403)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(add, {"title": "Nope"}).status_code, 404)
        self.assertEqual(TripIdea.objects.count(), 1)

    def test_the_shelf_on_the_page(self):
        idea = self.idea(poi=self.castle, notes="Book the tour")
        Vote.objects.create(user=self.editor, idea=idea)
        placed = self.idea("Already on a day")
        placed.place_on(TripActivity.objects.create(trip=self.trip, day=self.day1, title="Already on a day"))
        shelf = self.shelf(self.page())
        self.assertIn("Ideas</span> <span class=\"text-zinc-500\">· 1</span>", shelf)
        self.assertIn(f'id="idea-{idea.pk}"', shelf)
        self.assertIn("Neuschwanstein Castle", shelf)
        self.assertIn(reverse("locations:poi_detail", args=["neuschwanstein"]), shelf)
        self.assertIn("Book the tour", shelf)
        self.assertIn("👍 1", shelf)
        self.assertIn("Added by Cora", shelf)
        self.assertIn("data-idea-place", shelf)
        self.assertNotIn("Already on a day", shelf)  # placed ideas leave the shelf

    def test_viewers_see_it_without_controls(self):
        self.idea()
        shelf = self.shelf(self.page(self.viewer))
        self.assertIn("Day trip to Salzburg", shelf)
        for marker in ("data-idea-place", "data-idea-option", "data-idea-add", 'data-vote'):
            self.assertNotIn(marker, shelf)

    def test_the_adder_or_an_editor_changes_it(self):
        idea = self.idea()
        other = User.objects.create_user("o2", "o2@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=self.trip, user=other, role=TripRole.COMMENTOR)
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url("idea_edit", idea)).status_code, 403)
        self.assertEqual(self.client.post(self.url("idea_delete", idea)).status_code, 403)
        self.client.force_login(self.commentor)
        self.client.post(self.url("idea_edit", idea), {"title": "Salzburg by train", "notes": "", "kind_hint": "travel"})
        idea.refresh_from_db()
        self.assertEqual((idea.title, idea.kind), ("Salzburg by train", "travel"))
        self.client.force_login(self.editor)
        self.client.post(self.url("idea_delete", idea))
        self.assertFalse(TripIdea.objects.exists())

    def test_votes_toggle(self):
        idea = self.idea()
        self.client.force_login(self.commentor)
        self.client.post(self.url("idea_vote", idea))
        self.assertEqual(idea.votes.count(), 1)
        response = self.client.post(self.url("idea_vote", idea), HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(idea.votes.count(), 0)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(self.url("idea_vote", idea)).status_code, 403)

    def test_in_the_history(self):
        self.idea()
        self.assertTrue(TripChange.objects.filter(item_type="tripidea", summary__startswith="Added idea").exists())

    def test_never_public(self):
        self.idea("Secret beer garden")
        self.trip.enable_public()
        response = self.client.get(reverse("public_trip", args=[self.trip.public_token]))
        self.assertNotContains(response, "Secret beer garden")


class PlaceTests(Fixture):
    def place(self, idea, day=None, kind=None, fetch=False):
        self.client.force_login(self.editor)
        data = {"day": (day or self.day2).pk, **({"kind": kind} if kind else {})}
        extra = {"HTTP_X_REQUESTED_WITH": "fetch"} if fetch else {}
        return self.client.post(self.url("idea_place", idea), data, **extra)

    def test_a_place_becomes_an_activity_with_its_link(self):
        idea = self.idea("Neuschwanstein", poi=self.castle, notes="Book the tour")
        response = self.place(idea, fetch=True)
        activity = TripActivity.objects.get()
        self.assertEqual(response.json()["anchor"], f"activity-{activity.pk}")
        self.assertEqual((activity.day, activity.title, activity.poi, activity.notes),
                         (self.day2, "Neuschwanstein", self.castle, "Book the tour"))
        idea.refresh_from_db()
        self.assertEqual(idea.placed, activity)
        self.assertIn(self.fussen, self.trip.cities.all())  # the place's city joins the trip

    def test_each_kind(self):
        food = self.idea("Augustiner Keller", poi=self.augustiner)
        self.assertEqual(food.kind, "eat")
        self.place(food)
        self.assertEqual(Meal.objects.get().poi, self.augustiner)
        self.place(self.idea("Hotel Laimer Hof", kind_hint="stay"))
        self.assertEqual(Lodging.objects.get().check_in, self.day2.date)
        self.place(self.idea("Train to Füssen", city=self.fussen, kind_hint="travel"))
        leg = TransportLeg.objects.get()
        self.assertEqual((leg.origin, leg.destination_city, leg.date), ("Munich", self.fussen, self.day2.date))
        self.place(self.idea("Oktoberfest 2027", event=self.okto27))
        self.assertEqual(TripActivity.objects.get().event, self.okto27)
        self.place(self.idea("Remember the rain jackets"))
        note = Section.objects.get()
        self.assertEqual((note.section_type, note.title), ("note", "Remember the rain jackets"))
        self.assertFalse(TripIdea.objects.filter(placed_id__isnull=True).exists())

    def test_the_kind_clicked_wins(self):
        self.place(self.idea("Augustiner Keller", poi=self.augustiner), kind="do")
        self.assertEqual(TripActivity.objects.get().poi, self.augustiner)
        self.assertFalse(Meal.objects.exists())

    def test_editors_only(self):
        idea = self.idea()
        self.client.force_login(self.commentor)
        self.assertEqual(self.client.post(self.url("idea_place", idea), {"day": self.day1.pk}).status_code, 403)

    def test_deleting_it_returns_the_idea(self):
        idea = self.idea("Neuschwanstein", poi=self.castle)
        self.place(idea)
        TripActivity.objects.get().delete()
        idea.refresh_from_db()
        self.assertFalse(idea.is_placed)
        self.assertIn(f'id="idea-{idea.pk}"', self.shelf(self.page()))

    def test_as_an_option_of_an_open_choice(self):
        group = OptionGroup.objects.create(trip=self.trip, day=self.day2, prompt="Afternoon")
        idea = self.idea("Neuschwanstein", poi=self.castle)
        self.client.force_login(self.editor)
        response = self.client.post(self.url("idea_option", idea), {"target": f"group-{group.pk}"})
        option = Option.objects.get()
        self.assertEqual((option.group, option.title), (group, "Neuschwanstein"))
        self.assertEqual(TripActivity.objects.get().option, option)  # its catalogue link comes along
        self.assertTrue(response["Location"].startswith(reverse("trips:group_edit", args=[self.trip.pk, group.pk])))
        idea.refresh_from_db()
        self.assertEqual(idea.placed, option)
        group.delete()  # the option goes with it, and the idea comes back
        idea.refresh_from_db()
        self.assertFalse(idea.is_placed)

    def test_as_an_option_of_a_new_choice(self):
        idea = self.idea("Salzburg")
        self.client.force_login(self.editor)
        self.client.post(self.url("idea_option", idea), {"target": f"day-{self.day1.pk}"})
        group = OptionGroup.objects.get()
        self.assertEqual((group.day, group.prompt, group.options.get().title), (self.day1, "Salzburg or …", "Salzburg"))
        self.assertFalse(TripActivity.objects.exists())  # a typed idea is just the option

    def test_counted(self):
        on_day, in_option, picked = self.idea("A"), self.idea("B"), self.idea("C")
        on_day.place_on(TripActivity.objects.create(trip=self.trip, day=self.day1, title="A"))
        group = OptionGroup.objects.create(trip=self.trip, day=self.day1, prompt="Afternoon")
        b, c = (Option.objects.create(group=group, title=t) for t in "BC")
        in_option.place_on(b)
        picked.place_on(c)
        self.assertEqual(ideas.counted(self.trip), {on_day.pk})
        group.pick(c)
        self.assertEqual(ideas.counted(self.trip), {on_day.pk, picked.pk})


class CatalogueTests(Fixture):
    def test_add_to_a_trip_from_a_place_page(self):
        self.client.force_login(self.commentor)
        page = self.client.get(reverse("locations:poi_detail", args=["neuschwanstein"])).content.decode()
        url = reverse("trips:idea_from_catalogue", args=["poi", self.castle.pk])
        self.assertIn(url, page)
        listing = self.client.get(url)
        self.assertContains(listing, "Bavaria")
        self.client.post(url, {"trip": self.trip.pk})
        idea = TripIdea.objects.get()
        self.assertEqual((idea.title, idea.poi, idea.added_by), ("Neuschwanstein Castle", self.castle, self.commentor))
        self.client.post(url, {"trip": self.trip.pk})  # once per trip
        self.assertEqual(TripIdea.objects.count(), 1)

    def test_only_trips_you_may_comment_on(self):
        self.client.force_login(self.viewer)
        url = reverse("trips:idea_from_catalogue", args=["event", self.okto27.pk])
        self.assertNotContains(self.client.get(url), "Bavaria")
        self.assertEqual(self.client.post(url, {"trip": self.trip.pk}).status_code, 404)

    def test_each_catalogue_page_has_the_button(self):
        self.client.force_login(self.editor)
        for kind, obj, page in (("activity", self.okto, reverse("activities:activity_detail", args=["oktoberfest"])),
                                ("event", self.okto27, reverse("events:event_detail", args=["oktoberfest-2027"])),
                                ("city", self.munich, reverse("locations:city_detail", args=["munich"]))):
            self.assertContains(self.client.get(page), reverse("trips:idea_from_catalogue", args=[kind, obj.pk]))

    def test_unpublished_items_are_refused(self):
        self.castle.approval_status = ApprovalStatus.PENDING
        self.castle.save()
        self.client.force_login(self.commentor)
        self.assertEqual(self.client.get(reverse("trips:idea_from_catalogue", args=["poi", self.castle.pk])).status_code, 404)


class MapTests(Fixture):
    def test_faint_pins_for_shelf_ideas_with_a_place(self):
        self.idea("Neuschwanstein", poi=self.castle)
        self.idea("Oktoberfest", activity=self.okto)
        self.idea("Somewhere unknown")
        self.idea("On a day", city=self.fussen).place_on(TripActivity.objects.create(trip=self.trip, day=self.day1, title="x"))
        self.client.force_login(self.viewer)
        data = self.client.get(reverse("trips:trip_map_data", args=[self.trip.pk])).json()
        pins = {f["properties"]["name"]: f for f in data["features"] if f["properties"].get("layer") == "ideas"}
        self.assertEqual(set(pins), {"Neuschwanstein", "Oktoberfest"})
        self.assertEqual(pins["Neuschwanstein"]["geometry"]["coordinates"], [10.75, 47.56])
        self.assertEqual(pins["Oktoberfest"]["geometry"]["coordinates"], [11.6, 48.1])  # its city
        self.assertEqual(pins["Neuschwanstein"]["properties"]["marker"], "idea")
        page = self.client.get(reverse("trips:trip_map", args=[self.trip.pk])).content.decode()
        self.assertIn('<input type="checkbox" data-layer="ideas">', page)  # off until switched on

    def test_an_ideas_city_is_used(self):
        from apps.trips import trip_cities
        self.idea("Neuschwanstein", poi=self.castle)
        self.assertIn("the idea “Neuschwanstein”", trip_cities.used_by(self.trip)[self.fussen.pk])
