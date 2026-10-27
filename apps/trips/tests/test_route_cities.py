"""Cities that keep themselves up to date, the route builder and the route strip
(docs/plans/day-first-planning.md, P1)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.activities.models import ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import City, Country, POI
from apps.trips import route, trip_cities
from apps.trips.forms import DayForm, TripForm
from apps.trips.models import (Day, Lodging, Meal, Section, TransportLeg, Trip, TripActivity, TripChange, TripGrant,
                               TripRole)

User = get_user_model()
APPROVED = ApprovalStatus.APPROVED


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Alps", start_date=date(2027, 9, 18), end_date=date(2027, 9, 27),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU",
                                         continent="Europe", currency_code="EUR", approval_status=APPROVED)
        self.at = Country.objects.create(name="Austria", slug="at", iso_code="AT", iso3_code="AUT",
                                         continent="Europe", currency_code="EUR", approval_status=APPROVED)

        def city(name, country, **extra):
            extra.setdefault("approval_status", APPROVED)
            return City.objects.create(name=name, slug=name.lower(), country=country, latitude=0, longitude=0,
                                       timezone="Europe/Berlin" if country == self.de else "Europe/Vienna", **extra)

        self.city = city
        self.munich, self.salzburg, self.vienna = city("Munich", self.de), city("Salzburg", self.at), city("Vienna", self.at)


class SyncTests(Fixture):
    def test_every_source_adds_its_city_and_nothing_is_removed(self):
        augsburg, linz, graz, hall, bonn, innsbruck = (self.city(n, c) for n, c in (
            ("Augsburg", self.de), ("Linz", self.at), ("Graz", self.at), ("Hall", self.at), ("Bonn", self.de),
            ("Innsbruck", self.at)))
        day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18), city=self.munich)
        Lodging.objects.create(trip=self.trip, name="Hotel", city=augsburg, check_in=date(2027, 9, 18),
                               check_out=date(2027, 9, 19))
        TransportLeg.objects.create(trip=self.trip, origin="Linz", destination="Graz", origin_city=linz,
                                    destination_city=graz, date=day.date)
        TripActivity.objects.create(trip=self.trip, day=day, title="Mine", poi=POI.objects.create(
            name="Salt mine", slug="salt-mine", city=hall, latitude=0, longitude=0, approval_status=APPROVED))
        Meal.objects.create(day=day, name="Lunch", meal_type="lunch", poi=POI.objects.create(
            name="Café", slug="cafe", city=bonn, latitude=0, longitude=0, approval_status=APPROVED))
        category, _ = ActivityCategory.objects.get_or_create(name="Festival", defaults={"slug": "festival"})
        Section.objects.create(day=day, section_type="free_text", title="Fest", event=Event.objects.create(
            name="Fest", slug="fest", description="d", category=category, start_date=day.date, end_date=day.date,
            city=innsbruck, approval_status=APPROVED))
        self.trip.cities.set([self.vienna])  # on the trip without being used
        self.assertEqual(trip_cities.sync(self.trip), 7)
        self.assertEqual(set(self.trip.cities.all()),
                         {self.vienna, self.munich, augsburg, linz, graz, hall, bonn, innsbruck})
        self.assertEqual(trip_cities.sync(self.trip), 0)
        self.assertEqual(trip_cities.used_by(self.trip)[self.munich.pk], ["Day 1"])
        self.assertEqual(trip_cities.used_by(self.trip)[linz.pk], ["Linz → Graz"])

    def test_edit_trip_refuses_to_remove_a_city_in_use(self):
        Day.objects.create(trip=self.trip, day_number=3, date=date(2027, 9, 20), city=self.munich)
        Lodging.objects.create(trip=self.trip, name="Hotel Laimer Hof", city=self.munich, check_in=date(2027, 9, 20),
                               check_out=date(2027, 9, 21))
        self.trip.cities.set([self.munich, self.vienna])
        data = {"name": "Alps", "start_date": "2027-09-18", "end_date": "2027-09-27", "status": "starting",
                "home_currency": "EUR", "structure": self.trip.structure}
        form = TripForm({**data, "cities": [self.vienna.pk]}, instance=self.trip, user=self.editor)
        self.assertFalse(form.is_valid())
        self.assertIn("Munich is used by Day 3, Hotel Laimer Hof", form.errors["cities"][0])
        form = TripForm({**data, "cities": [self.munich.pk]}, instance=self.trip, user=self.editor)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertEqual(list(self.trip.cities.all()), [self.munich])

    def test_a_city_the_member_just_added_is_usable_at_once(self):
        from apps.core.current import acting_as
        mine = self.city("Hallstatt", self.at, approval_status=ApprovalStatus.PENDING, submitted_by=self.editor)
        theirs = self.city("Gosau", self.at, approval_status=ApprovalStatus.PENDING, submitted_by=self.viewer)
        day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        with acting_as(self.editor):
            form = DayForm({"day_number": 1, "date": "2027-09-18", "city": mine.pk}, instance=day, trip=self.trip)
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
            self.assertFalse(DayForm({"day_number": 1, "date": "2027-09-18", "city": theirs.pk}, instance=day,
                                     trip=self.trip).is_valid())
        self.assertIn(mine, self.trip.cities.all())
        with acting_as(self.viewer):  # on the trip now, so it stays a choice for everyone on it
            self.assertTrue(DayForm({"day_number": 1, "date": "2027-09-18", "city": mine.pk}, instance=day,
                                    trip=self.trip).is_valid())

    def test_the_forms_render_the_search_box(self):
        self.client.force_login(self.editor)
        day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        self.trip.cities.set([self.munich])
        for url in (reverse("trips:day_edit", args=[self.trip.pk, day.pk]),
                    reverse("trips:stay_new", args=[self.trip.pk, day.pk]),
                    reverse("trips:trip_edit", args=[self.trip.pk])):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertContains(page, "data-city-search")
                self.assertContains(page, "<noscript>")


class PlanTests(Fixture):
    def stops(self, *nights):
        return list(zip((self.munich, self.salzburg, self.vienna), nights))

    def test_it_lays_the_route_over_the_days(self):
        plan = route.plan(self.trip, self.stops(3, 2, 4), [], [], [])
        self.assertEqual([(d.day, c.name) for d, c in plan.dates],
                         [(18, "Munich"), (19, "Munich"), (20, "Munich"), (21, "Salzburg"), (22, "Salzburg"),
                          (23, "Vienna"), (24, "Vienna"), (25, "Vienna"), (26, "Vienna"), (27, "Vienna")])
        self.assertEqual([(d.day, a.name, b.name) for d, a, b, _ in plan.legs],
                         [(21, "Munich", "Salzburg"), (23, "Salzburg", "Vienna")])
        self.assertEqual([(c.name, i.day, o.day) for c, i, o, _ in plan.stays],
                         [("Munich", 18, 21), ("Salzburg", 21, 23), ("Vienna", 23, 27)])
        self.assertEqual((plan.route_nights, plan.trip_nights, plan.cut, plan.blank_from), (9, 9, False, None))
        self.assertEqual(plan.summary, "Munich (3) → Salzburg (2) → Vienna (4)")

    def test_a_route_that_doesnt_add_up(self):
        short = route.plan(self.trip, self.stops(3, 2), [], [], [])
        self.assertEqual(short.blank_from, date(2027, 9, 23))
        self.assertEqual(short.dates[-1], (date(2027, 9, 22), self.salzburg))
        long = route.plan(self.trip, self.stops(3, 2, 7), [], [], [])
        self.assertTrue(long.cut)
        self.assertEqual(long.dates[-1], (date(2027, 9, 27), self.vienna))
        self.assertEqual(long.stays[-1][2], date(2027, 9, 27))
        extended = route.plan(self.trip, self.stops(3, 2, 7), [], [], [], extend=True)
        self.assertEqual((extended.new_end, extended.dates[-1][0]), (date(2027, 9, 30), date(2027, 9, 30)))

    def test_apply_fills_days_once_and_keeps_set_ones(self):
        day1 = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 9, 18))
        Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 19), city=self.vienna)  # a day trip

        def run(**options):
            plan = route.plan(self.trip, self.stops(3, 2, 4), list(self.trip.days.all()),
                              list(self.trip.transport.all()), list(self.trip.lodging.all()))
            return plan, route.apply(self.trip, plan, **options)

        before = TripChange.objects.count()
        plan, counts = run()
        self.assertEqual([(d.day_number, c.name) for _, d, _, c in plan.conflicts], [(2, "Munich")])
        self.assertEqual(counts, {"days": 1, "new_days": 8, "legs": 2, "stays": 3})
        days = {d.day_number: d.city.name for d in self.trip.days.select_related("city")}
        self.assertEqual(days, {1: "Munich", 2: "Vienna", 3: "Munich", 4: "Salzburg", 5: "Salzburg", 6: "Vienna",
                                7: "Vienna", 8: "Vienna", 9: "Vienna", 10: "Vienna"})
        leg = self.trip.transport.get(date=date(2027, 9, 21))
        self.assertEqual((leg.mode, leg.origin, leg.destination, leg.is_planned, leg.destination_timezone),
                         ("other", "Munich", "Salzburg", True, "Europe/Vienna"))
        stay = self.trip.lodging.get(city=self.munich)
        self.assertEqual((stay.name, stay.address, stay.check_out, stay.currency),
                         ("Stay in Munich", "", date(2027, 9, 21), "EUR"))
        self.assertEqual(set(self.trip.cities.all()), {self.munich, self.salzburg, self.vienna})
        self.assertEqual(TripChange.objects.count(), before + 1)  # one history line
        self.assertTrue(TripChange.objects.latest("pk").summary.startswith("Route set: Munich (3) → Salzburg (2)"))

        _, again = run(replace=True)  # nothing twice; Replace changes the day trip
        self.assertEqual(again, {"days": 1, "new_days": 0, "legs": 0, "stays": 0})
        self.assertEqual(self.trip.days.get(day_number=2).city, self.munich)
        day1.refresh_from_db()
        self.assertEqual(day1.city, self.munich)

    def test_extending_moves_the_end_date(self):
        plan = route.plan(self.trip, self.stops(3, 2, 7), [], [], [], extend=True)
        route.apply(self.trip, plan, make_legs=False, make_stays=False)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.end_date, date(2027, 9, 30))
        self.assertEqual(self.trip.days.count(), 13)
        self.assertFalse(self.trip.transport.exists() or self.trip.lodging.exists())


class RouteViewTests(Fixture):
    def url(self):
        return reverse("trips:trip_route", args=[self.trip.pk])

    def rows(self, *stops, **extra):
        data = {"form-TOTAL_FORMS": "4", "form-INITIAL_FORMS": "0", **extra}
        for i in range(4):
            city, nights = stops[i] if i < len(stops) else ("", "")
            data[f"form-{i}-city"] = getattr(city, "pk", city)
            data[f"form-{i}-nights"] = nights
        return data

    def test_only_editors(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.client.force_login(User.objects.create_user("x", "x@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_it_starts_from_the_days_cities(self):
        for n, city in enumerate([self.munich, self.munich, self.salzburg, self.salzburg], start=1):
            Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 17 + n), city=city)
        self.client.force_login(self.editor)
        formset = self.client.get(self.url()).context["formset"]
        self.assertEqual([(f.initial.get("city"), f.initial.get("nights")) for f in formset.forms[:2]],
                         [(self.munich, 2), (self.salzburg, 2)])

    def test_preview_then_save(self):
        self.client.force_login(self.editor)
        page = self.client.post(self.url(), self.rows((self.munich, 3), (self.salzburg, 2), legs="on", stays="on"))
        self.assertContains(page, "Munich (3) → Salzburg (2)")
        self.assertContains(page, "shorter than the trip")
        self.assertContains(page, "data-route-save")
        self.assertFalse(self.trip.days.exists())  # a preview saves nothing
        response = self.client.post(self.url(), self.rows((self.munich, 3), (self.salzburg, 6), legs="on",
                                                          save="1"))
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk]) + "#days",
                             fetch_redirect_response=False)
        self.assertEqual(self.trip.days.count(), 10)
        self.assertEqual(self.trip.transport.count(), 1)
        self.assertFalse(self.trip.lodging.exists())  # unticked
        self.assertEqual(self.client.post(self.url(), self.rows((self.munich, ""))).status_code, 200)  # no nights


class StripTests(Fixture):
    def test_runs_and_the_strip(self):
        for n, city in enumerate([self.munich, self.munich, None, self.salzburg, self.munich], start=1):
            Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 17 + n), city=city)
        runs = route.runs(list(self.trip.days.select_related("city")))
        self.assertEqual([(r.city.name, len(r.days), r.first.day_number) for r in runs],
                         [("Munich", 2, 1), ("Salzburg", 1, 4), ("Munich", 1, 5)])
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        strip = html[html.index("data-route-strip"):html.index("</nav>", html.index("data-route-strip"))]
        self.assertIn('href="#day-1">Munich <span class="text-zinc-500">(2)</span>', strip)
        self.assertIn('href="#day-4">Salzburg', strip)
        self.assertIn("Edit route", strip)
        self.client.force_login(self.viewer)
        self.assertNotContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), "Edit route")

    def test_editors_are_offered_the_builder_on_a_new_trip(self):
        self.client.force_login(self.editor)
        page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(page, "Set the route")
        self.client.force_login(self.viewer)
        self.assertNotContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), "Set the route")
