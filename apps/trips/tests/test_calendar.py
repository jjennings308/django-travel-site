"""The trip calendar feed and its page (site roadmap R4)."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse
from icalendar import Calendar

from apps.trips.models import (
    Confirmation, Day, Lodging, Meal, TransportLeg, Traveler, Trip, TripActivity, TripCalendarToken, TripGrant,
    TripRole,
)

User = get_user_model()


@override_settings(SITE_URL="https://example.test")
class CalendarFixture(TestCase):
    def setUp(self):
        ContentType.objects.clear_cache()
        ContentType.objects.get_for_models(TransportLeg, TripActivity, Meal, Lodging)  # warm, as in production
        self.owner = User.objects.create_user("owner", "owner@example.com", "pw-1234-abcd", first_name="Olive")
        self.viewer = User.objects.create_user("vera", "vera@example.com", "pw-1234-abcd", first_name="Vera")
        self.trip = Trip.objects.create(name="Bavaria", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.owner)
        TripGrant.objects.create(trip=self.trip, user=self.owner, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.olive = Traveler.objects.get(user=self.owner)
        self.vera = Traveler.objects.get(user=self.viewer)
        self.d1, self.d2, self.d3 = (Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 17 + n))
                                     for n in range(1, 4))
        self.flight = TransportLeg.objects.create(
            trip=self.trip, mode="plane", operator="Lufthansa", service_number="LH 401", origin="JFK",
            destination="FRA", departure_at=datetime(2027, 9, 18, 22, 0, tzinfo=dt_timezone.utc),
            arrival_at=datetime(2027, 9, 19, 6, 0, tzinfo=dt_timezone.utc),
            origin_timezone="America/New_York", destination_timezone="Europe/Berlin")
        self.planned = TransportLeg.objects.create(trip=self.trip, mode="train", origin="Frankfurt Hbf",
                                                   destination="Augsburg Hbf", date=self.d2.date,
                                                   est_duration=timedelta(minutes=45))
        self.tour = TripActivity.objects.create(trip=self.trip, day=self.d2, title="Brewery tour", kind="tour",
                                                provider="Augustiner", start_time=time(14, 30), place_text="Old town")
        self.tour.travelers.add(self.olive)
        self.stroll = TripActivity.objects.create(trip=self.trip, day=self.d3, title="Stroll")
        self.dinner = Meal.objects.create(day=self.d2, name="Bräustüberl", meal_type="dinner",
                                          reserved_time=time(19, 0))
        Meal.objects.create(day=self.d2, name="Idea only", meal_type="lunch")
        self.stay = Lodging.objects.create(trip=self.trip, name="Hotel Drei Mohren", address="Maximilianstr. 40\nAugsburg",
                                           check_in=date(2027, 9, 19), check_out=date(2027, 9, 21))
        Confirmation.attach_number(self.trip, "GCH7JS", self.flight, provider="Lufthansa")
        Confirmation.attach_number(self.trip, "HOTEL-77", self.stay, provider="Booking.com")

    def feed(self, user=None, mine=False):
        token = TripCalendarToken.for_user(self.trip, user or self.viewer)
        url = reverse("trips:trip_calendar_feed", args=[token.token]) + ("?mine=1" if mine else "")
        return self.client.get(url)

    def events(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        cal = Calendar.from_ical(response.content)
        return {str(event["UID"]).split("@")[0]: event for event in cal.walk("VEVENT")}


class FeedTests(CalendarFixture):
    def test_every_kind_of_item(self):
        events = self.events(self.feed())
        self.assertEqual(set(events), {f"leg-{self.flight.pk}", f"leg-{self.planned.pk}", f"activity-{self.tour.pk}",
                                       f"activity-{self.stroll.pk}", f"meal-{self.dinner.pk}", f"stay-{self.stay.pk}"})

    def test_legs_in_utc_with_operator_number_and_confirmation(self):
        event = self.events(self.feed())[f"leg-{self.flight.pk}"]
        self.assertEqual(event.decoded("dtstart"), datetime(2027, 9, 18, 22, 0, tzinfo=dt_timezone.utc))
        self.assertIn("DTSTART:20270918T220000Z", event.to_ical().decode())
        self.assertEqual(str(event["SUMMARY"]), "✈ JFK → FRA")
        self.assertEqual(str(event["LOCATION"]), "JFK")
        description = str(event["DESCRIPTION"])
        self.assertIn("Lufthansa LH 401", description)
        self.assertIn("Confirmation: GCH7JS (Lufthansa)", description)
        self.assertIn(f"https://example.test/trips/{self.trip.pk}/?item=leg-{self.flight.pk}#leg-{self.flight.pk}", description)

    def test_activities_and_meals_are_floating_local_times(self):
        events = self.events(self.feed())
        tour = events[f"activity-{self.tour.pk}"]
        self.assertIn("DTSTART:20270919T143000\r\n", tour.to_ical().decode())  # no Z, no TZID
        self.assertEqual(tour.decoded("dtend"), datetime(2027, 9, 19, 15, 30))
        self.assertEqual(str(tour["LOCATION"]), "Old town")
        dinner = events[f"meal-{self.dinner.pk}"]
        self.assertEqual(str(dinner["SUMMARY"]), "🍽 Dinner: Bräustüberl")
        self.assertEqual(dinner.decoded("dtstart"), datetime(2027, 9, 19, 19, 0))

    def test_untimed_items_are_all_day_and_stays_span_their_nights(self):
        events = self.events(self.feed())
        planned = events[f"leg-{self.planned.pk}"]
        self.assertEqual((planned.decoded("dtstart"), planned.decoded("dtend")), (date(2027, 9, 19), date(2027, 9, 20)))
        self.assertIn("(planned)", str(planned["SUMMARY"]))
        self.assertIn("~45 min", str(planned["DESCRIPTION"]))
        self.assertEqual(events[f"activity-{self.stroll.pk}"].decoded("dtstart"), date(2027, 9, 20))
        stay = events[f"stay-{self.stay.pk}"]
        self.assertEqual((stay.decoded("dtstart"), stay.decoded("dtend")), (date(2027, 9, 19), date(2027, 9, 21)))
        self.assertEqual(str(stay["LOCATION"]), "Maximilianstr. 40 Augsburg")
        self.assertIn("HOTEL-77", str(stay["DESCRIPTION"]))

    def test_uids_are_stable_across_fetches(self):
        self.assertEqual(set(self.events(self.feed())), set(self.events(self.feed())))

    def test_calendar_properties(self):
        cal = Calendar.from_ical(self.feed().content)
        self.assertEqual(str(cal["X-WR-CALNAME"]), "Bavaria")
        self.assertIn("REFRESH-INTERVAL;VALUE=DURATION:PT4H", cal.to_ical().decode())

    def test_mine_keeps_what_the_viewer_is_on(self):
        self.d3.travelers.add(self.olive)  # a split day: Olive only
        mine = self.events(self.feed(mine=True))
        self.assertNotIn(f"activity-{self.tour.pk}", mine)  # Olive's tour
        self.assertNotIn(f"activity-{self.stroll.pk}", mine)  # on Olive's day
        self.assertIn(f"leg-{self.planned.pk}", mine)  # blank day travellers = everyone
        self.assertIn(f"stay-{self.stay.pk}", mine)
        everything = self.events(self.feed(mine=False))
        self.assertIn(f"activity-{self.tour.pk}", everything)
        self.assertIn(f"activity-{self.tour.pk}", self.events(self.feed(user=self.owner, mine=True)))

    def test_fixed_query_count(self):
        token = TripCalendarToken.for_user(self.trip, self.viewer)
        url = reverse("trips:trip_calendar_feed", args=[token.token])
        # token+trip+user, the grant, days, day travellers, legs, activities, their travellers,
        # meals, stays, confirmation links, (day-first plan P4) the undecided groups and their options, and
        # (P5) who takes each option of a split group
        from apps.trips.models import Option, OptionGroup
        group = OptionGroup.objects.create(trip=self.trip, day=self.d1, prompt="Afternoon")
        Option.objects.create(group=group, title="Castle")
        with self.assertNumQueries(13):
            self.client.get(url)
        TripActivity.objects.create(trip=self.trip, day=self.d1, title="More", start_time=time(9, 0))
        Meal.objects.create(day=self.d3, name="More", meal_type="lunch", reserved_time=time(12, 0))
        OptionGroup.objects.create(trip=self.trip, day=self.d3, prompt="Dinner")
        with self.assertNumQueries(13):
            self.client.get(url)


class FeedAccessTests(CalendarFixture):
    def test_reset_token_is_a_404(self):
        old = TripCalendarToken.for_user(self.trip, self.viewer)
        new = old.reset()
        self.assertEqual(self.client.get(reverse("trips:trip_calendar_feed", args=[old.token])).status_code, 404)
        self.assertEqual(self.client.get(reverse("trips:trip_calendar_feed", args=[new.token])).status_code, 200)

    def test_losing_access_kills_the_feed(self):
        token = TripCalendarToken.for_user(self.trip, self.viewer)
        TripGrant.objects.filter(trip=self.trip, user=self.viewer).delete()
        self.assertEqual(self.client.get(reverse("trips:trip_calendar_feed", args=[token.token])).status_code, 404)

    def test_inactive_owner_or_deleted_trip(self):
        token = TripCalendarToken.for_user(self.trip, self.viewer)
        url = reverse("trips:trip_calendar_feed", args=[token.token])
        User.objects.filter(pk=self.viewer.pk).update(is_active=False)
        self.assertEqual(self.client.get(url).status_code, 404)
        User.objects.filter(pk=self.viewer.pk).update(is_active=True)
        Trip.objects.filter(pk=self.trip.pk).update(deleted_at=datetime.now(dt_timezone.utc))
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_unknown_token(self):
        self.assertEqual(self.client.get(reverse("trips:trip_calendar_feed", args=["nope"])).status_code, 404)


class PageTests(CalendarFixture):
    def test_viewer_gets_their_own_link(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("trips:trip_calendar", args=[self.trip.pk]))
        token = TripCalendarToken.objects.get(trip=self.trip, user=self.viewer, revoked_at=None)
        self.assertContains(response, f"/trips/calendar/{token.token}.ics")
        self.assertContains(response, "confirmation numbers")
        self.assertContains(response, "webcal://")
        self.client.get(reverse("trips:trip_calendar", args=[self.trip.pk]))
        self.assertEqual(TripCalendarToken.objects.filter(trip=self.trip, user=self.viewer).count(), 1)

    def test_people_get_different_links(self):
        self.assertNotEqual(TripCalendarToken.for_user(self.trip, self.viewer).token,
                            TripCalendarToken.for_user(self.trip, self.owner).token)

    def test_reset(self):
        self.client.force_login(self.viewer)
        old = TripCalendarToken.for_user(self.trip, self.viewer).token
        response = self.client.post(reverse("trips:trip_calendar_reset", args=[self.trip.pk]))
        self.assertRedirects(response, reverse("trips:trip_calendar", args=[self.trip.pk]))
        live = TripCalendarToken.objects.get(trip=self.trip, user=self.viewer, revoked_at=None)
        self.assertNotEqual(live.token, old)

    def test_no_grant_is_a_404(self):
        stranger = User.objects.create_user("stranger", "s@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("trips:trip_calendar", args=[self.trip.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("trips:trip_calendar_reset", args=[self.trip.pk])).status_code, 404)
        self.assertFalse(TripCalendarToken.objects.filter(user=stranger).exists())

    def test_public_view_never_links_the_calendar(self):
        self.trip.enable_public()
        response = self.client.get(reverse("public_trip", args=[self.trip.public_token]))
        self.assertNotContains(response, "/calendar/")
