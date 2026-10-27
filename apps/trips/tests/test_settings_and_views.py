"""Edit trip becomes Settings, the days follow new dates, and the trip-wide views are read-only and open
items on the trip page (docs/plans/day-first-planning.md, P7)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips import day_fit
from apps.trips.models import (Day, Lodging, Meal, OptionGroup, Section, TransportLeg, Trip, TripActivity,
                               TripGrant, TripIdea, TripRole)

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Alps", start_date=date(2027, 9, 18), end_date=date(2027, 9, 20),
                                        created_by=self.editor, home_currency="EUR")
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 17 + n)) for n in (1, 2, 3)]
        self.detail = reverse("trips:trip_detail", args=[self.trip.pk])

    def get(self, name, user=None, *args):
        self.client.force_login(user or self.editor)
        return self.client.get(reverse(f"trips:{name}", args=[self.trip.pk, *args]))

    def payload(self, **changes):
        data = {"name": self.trip.name, "start_date": "2027-09-18", "end_date": "2027-09-20", "status": "starting",
                "home_currency": "EUR", "home_currency_other": "", "destination": "", "notes": "", "new_traveler_name": ""}
        data.update(changes)
        return data


class SettingsTests(Fixture):
    def test_the_old_address_redirects(self):
        response = self.get("trip_edit")
        self.assertRedirects(response, reverse("trips:trip_settings", args=[self.trip.pk]))
        self.assertEqual(self.get("trip_edit", self.viewer).status_code, 403)
        self.assertEqual(self.get("trip_settings", self.viewer).status_code, 403)

    def test_settings_saves(self):
        self.client.force_login(self.editor)
        response = self.client.post(reverse("trips:trip_settings", args=[self.trip.pk]), self.payload(name="Alps 2027"))
        self.assertRedirects(response, self.detail, fetch_redirect_response=False)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.name, "Alps 2027")

    def test_the_page(self):
        html = self.get("trip_settings").content.decode()
        self.assertIn("<h1 class=\"page-title\">Settings</h1>", html)
        self.assertIn(reverse("trips:trip_people", args=[self.trip.pk]), html)
        self.assertIn('id="loose-confirmations"', html)
        self.assertIn('id="checklists"', html)
        self.assertIn(reverse("trips:trip_bookings", args=[self.trip.pk]) + "#stays-legs", html)  # moved there
        self.assertNotIn("data-stays-legs", html)

    def test_the_trip_page_header(self):
        html = self.get("trip_detail").content.decode()
        self.assertIn("data-settings-link>Settings</a>", html)
        self.assertNotIn(">Edit trip</a>", html)
        self.assertIn(reverse("trips:trip_bookings", args=[self.trip.pk]), html)
        self.assertIn(reverse("trips:trip_todo", args=[self.trip.pk]), html)
        self.assertNotIn("data-jump-ideas", html)
        TripIdea.objects.create(trip=self.trip, title="Salzburg")
        self.assertIn('<a href="#ideas" data-jump-ideas>Ideas</a>', self.get("trip_detail").content.decode())
        self.assertNotIn("data-settings-link", self.get("trip_detail", self.viewer).content.decode())


class DateChangeTests(Fixture):
    def post(self, **changes):
        self.client.force_login(self.editor)
        return self.client.post(reverse("trips:trip_settings", args=[self.trip.pk]), self.payload(**changes))

    def test_unchanged_dates_go_back_to_the_trip(self):
        self.assertRedirects(self.post(name="Alps!"), self.detail, fetch_redirect_response=False)

    def test_longer_dates_offer_days(self):
        response = self.post(end_date="2027-09-22")
        fit = reverse("trips:trip_days_fit", args=[self.trip.pk])
        self.assertRedirects(response, fit)
        page = self.client.get(fit).content.decode()
        self.assertIn('name="add" value="2027-09-21" checked', page)
        self.assertIn('name="add" value="2027-09-22" checked', page)
        self.assertEqual(Day.objects.filter(trip=self.trip).count(), 3)  # nothing until saved
        self.client.post(fit, {"add": ["2027-09-21", "2027-09-22"]})
        self.assertEqual(list(self.trip.days.values_list("day_number", "date")),
                         [(n, date(2027, 9, 17 + n)) for n in range(1, 6)])

    def test_moved_dates_offer_both_and_renumber(self):
        Meal.objects.create(day=self.days[0], name="Lunch", meal_type="lunch")
        self.post(start_date="2027-09-19", end_date="2027-09-21")
        self.trip.refresh_from_db()
        found = day_fit.plan(self.trip)
        self.assertEqual(found["missing"], [date(2027, 9, 21)])
        self.assertEqual([d.pk for d in found["outside"]], [self.days[0].pk])
        self.assertEqual(found["outside"][0].contents, ["1 meal"])
        page = self.client.get(reverse("trips:trip_days_fit", args=[self.trip.pk])).content.decode()
        self.assertIn(f'name="remove" value="{self.days[0].pk}">', page)  # not ticked: it has a meal
        self.assertIn("1 meal would be deleted", page)
        self.client.post(reverse("trips:trip_days_fit", args=[self.trip.pk]),
                         {"add": ["2027-09-21"], "remove": [self.days[0].pk]})
        self.assertEqual(list(self.trip.days.values_list("day_number", "date")),
                         [(1, date(2027, 9, 19)), (2, date(2027, 9, 20)), (3, date(2027, 9, 21))])
        self.assertFalse(Meal.objects.exists())

    def test_a_kept_day_stays(self):
        self.post(start_date="2027-09-19")
        self.client.post(reverse("trips:trip_days_fit", args=[self.trip.pk]), {})
        self.assertEqual(self.trip.days.count(), 3)

    def test_only_offered_days_change(self):
        self.post(end_date="2027-09-21")
        self.client.post(reverse("trips:trip_days_fit", args=[self.trip.pk]),
                         {"add": ["2030-01-01", "2027-09-21"], "remove": [self.days[1].pk]})
        self.assertEqual(self.trip.days.count(), 4)  # the inside day isn't removed, the far date isn't added

    def test_editors_only(self):
        self.assertEqual(self.get("trip_days_fit", self.viewer).status_code, 403)


class ReadOnlyViewTests(Fixture):
    def setUp(self):
        super().setUp()
        self.leg = TransportLeg.objects.create(trip=self.trip, date=self.days[1].date, mode="flight", origin="MUC",
                                               destination="LHR")
        self.stay = Lodging.objects.create(trip=self.trip, name="Hotel Laimer Hof", check_in=self.days[0].date,
                                           check_out=self.days[2].date)

    def item(self, anchor):
        return f'href="{self.detail}?item={anchor}#{anchor}"'

    def test_bookings_for_everyone_without_forms(self):
        html = self.get("trip_bookings", self.viewer).content.decode()
        main = html[html.index('<nav class="crumbs">'):]
        self.assertNotIn('method="post"', main)
        for anchor in (f"leg-{self.leg.pk}", f"stay-{self.stay.pk}"):
            self.assertIn(self.item(anchor), html)
        self.assertIn('id="not-booked"', html)  # a flight and a stay with no confirmation

    def test_todo_lists_choices_then_not_booked_then_todos(self):
        OptionGroup.objects.create(trip=self.trip, day=self.days[1], prompt="Afternoon")
        self.trip.booking_tasks.create(title="Buy rail passes")
        html = self.get("trip_todo", self.viewer).content.decode()
        self.assertLess(html.index("data-open-groups"), html.index('id="not-booked"'))
        self.assertLess(html.index('id="not-booked"'), html.index("data-open-tasks"))
        nb = html[html.index('id="not-booked"'):html.index("data-open-tasks")]
        self.assertIn(self.item(f"stay-{self.stay.pk}"), nb)

    def test_the_map_lists_open_items(self):
        from apps.locations.models import City, Country
        country = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe")
        munich = City.objects.create(name="Munich", slug="munich", country=country, latitude=48, longitude=11)
        london = City.objects.create(name="London", slug="london", country=country, latitude=51, longitude=0)
        self.leg.origin_city, self.leg.destination_city = munich, london
        self.leg.save()
        self.days[0].city = munich
        self.days[0].save()
        html = self.get("trip_map", self.viewer).content.decode()
        self.assertIn(self.item(f"leg-{self.leg.pk}"), html)

    def test_the_item_opens_on_the_trip_page(self):
        html = self.get("trip_detail").content.decode()
        self.assertIn(f'id="leg-{self.leg.pk}" data-panel="', html)  # what panel.js opens for ?item=
        self.assertIn("trips/panel.js", html)


class DayPageAddTests(Fixture):
    def test_the_day_page_has_one_line_add_and_comes_back(self):
        day = self.days[0]
        page = self.get("day_edit", None, day.pk).content.decode()
        self.assertIn("data-day-quick-add", page)
        here = reverse("trips:day_edit", args=[self.trip.pk, day.pk])
        response = self.client.post(reverse("trips:quick_add", args=[self.trip.pk, day.pk]),
                                    {"text": "Tour of the salt mine 10am", "next": here + "#on-this-day"})
        activity = TripActivity.objects.get()
        self.assertEqual(activity.day, day)
        self.assertIn(f"next={here}%23on-this-day", response["Location"])  # its page comes back to the day page
        note = self.client.post(reverse("trips:quick_add", args=[self.trip.pk, day.pk]),
                                {"text": "Bring cash", "kind": "note", "next": here})
        self.assertTrue(Section.objects.filter(day=day).exists())
        self.assertIn("next=", note["Location"])
