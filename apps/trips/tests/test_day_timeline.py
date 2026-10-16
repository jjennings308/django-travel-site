"""A day on the trip page (docs/plans/trip-page-ux.md, U3): stay lines, the timeline of legs,
activities and reserved meals in local time order, Any time, and Food ideas."""
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import AccountSettings
from apps.trips.models import Day, Lodging, Meal, TransportLeg, Trip, TripActivity, TripGrant, TripRole

User = get_user_model()
UTC = dt_timezone.utc


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 18), end_date=date(2027, 9, 21),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 17 + n)) for n in range(1, 5)]
        self.d2 = self.days[1]

    def page(self, user=None):
        self.client.force_login(user or self.viewer)
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))

    def day_html(self, html, number):
        start = html.index(f'id="day-{number}"')
        end = html.find(f'id="day-{number + 1}"', start)
        return html[start:end if end != -1 else None]


class TimelineTests(Fixture):
    def test_order_across_kinds_then_any_time_with_legs_in_order(self):
        leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="Frankfurt", destination="Augsburg",
                                          origin_timezone="Europe/Berlin", destination_timezone="Europe/Berlin",
                                          departure_at=datetime(2027, 9, 19, 8, 0, tzinfo=UTC),  # 10:00 Berlin
                                          arrival_at=datetime(2027, 9, 19, 10, 40, tzinfo=UTC))
        tour = TripActivity.objects.create(trip=self.trip, day=self.d2, title="Morning tour", start_time=time(9, 0))
        dinner = Meal.objects.create(day=self.d2, name="Fat Duck", meal_type="dinner", reserved_time=time(19, 30))
        later = TransportLeg.objects.create(trip=self.trip, origin="B2", destination="C2", date=self.d2.date, order=2)
        first = TransportLeg.objects.create(trip=self.trip, origin="A1", destination="B1", date=self.d2.date, order=1)
        loose = TripActivity.objects.create(trip=self.trip, day=self.d2, title="Stroll")
        idea = Meal.objects.create(day=self.d2, name="Café Idea", meal_type="lunch")
        page = self.page()
        d2 = next(d for d in page.context["days"] if d.pk == self.d2.pk)
        self.assertEqual([e["item"] for e in d2.timeline], [tour, leg, dinner])
        self.assertEqual([e["item"] for e in d2.any_time], [first, later, loose])
        self.assertEqual(d2.food_ideas, [idea])
        html = self.day_html(page.content.decode(), 2)
        for item_id in (f"activity-{tour.pk}", f"leg-{leg.pk}", f"meal-{dinner.pk}", f"leg-{first.pk}",
                        f"activity-{loose.pk}", f"meal-{idea.pk}"):
            self.assertEqual(html.count(f'id="{item_id}"'), 1)
        self.assertLess(html.index(f'id="activity-{tour.pk}"'), html.index(f'id="leg-{leg.pk}"'))
        self.assertLess(html.index(f'id="meal-{dinner.pk}"'), html.index("Any time"))
        self.assertLess(html.index("Any time"), html.index("Food ideas"))
        self.assertIn("Fat Duck", html[:html.index("Food ideas")])  # reserved: in the timeline
        self.assertNotIn("Fat Duck", html[html.index("Food ideas"):])

    def test_leg_times_stay_local_for_a_non_utc_reader(self):
        AccountSettings.objects.update_or_create(user=self.viewer, defaults={"timezone": "America/Los_Angeles"})
        TransportLeg.objects.create(trip=self.trip, mode="train", origin="Frankfurt", destination="Munich",
                                    origin_timezone="Europe/Berlin", destination_timezone="Europe/Berlin",
                                    departure_at=datetime(2027, 9, 19, 7, 0, tzinfo=UTC),
                                    arrival_at=datetime(2027, 9, 19, 10, 30, tzinfo=UTC))
        html = self.day_html(self.page(self.viewer).content.decode(), 2)
        self.assertIn("9:00 AM CEST", html)
        self.assertIn("12:30 PM CEST", html)
        self.assertNotIn("12:00 AM", html)  # never the reader's zone


class StayLineTests(Fixture):
    def test_check_in_card_middle_nights_and_check_out(self):
        hof = Lodging.objects.create(trip=self.trip, name="Hessischer Hof", check_in=self.days[0].date,
                                     check_out=self.days[2].date)
        augusta = Lodging.objects.create(trip=self.trip, name="Hotel Augusta", check_in=self.days[2].date,
                                         check_out=date(2027, 9, 25))
        html = self.page().content.decode()
        d1, d2, d3, d4 = (self.day_html(html, n) for n in range(1, 5))
        self.assertIn(f'id="stay-{hof.pk}"', d1)  # the card, on its check-in day
        self.assertIn(f'Sleeping: <a class="link-quiet font-medium" href="#stay-{hof.pk}">Hessischer Hof</a>', d2)
        self.assertIn(f'Check out: <a class="link-quiet font-medium" href="#stay-{hof.pk}">Hessischer Hof</a>', d3)
        self.assertIn(f'id="stay-{augusta.pk}"', d3)  # same day: check out, then the new card
        self.assertLess(d3.index("Check out:"), d3.index(f'id="stay-{augusta.pk}"'))
        self.assertIn("Sleeping: <a", d4)
        self.assertEqual(html.count(f'id="stay-{hof.pk}"'), 1)


class MealFormTests(Fixture):
    def test_day_page_saves_the_reservation_time(self):
        meal = Meal.objects.create(day=self.d2, name="Fat Duck", meal_type="dinner")
        self.client.force_login(self.editor)
        url = reverse("trips:day_edit", args=[self.trip.pk, self.d2.pk])
        formset = self.client.get(url).context["meal_formset"]
        self.assertIn("reserved_time", formset.forms[0].fields)
        from apps.trips.forms import MealFormSet
        prefix = formset.prefix
        data = {f"{prefix}-TOTAL_FORMS": "1", f"{prefix}-INITIAL_FORMS": "1", f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000", f"{prefix}-0-id": str(meal.pk), f"{prefix}-0-name": "Fat Duck",
                f"{prefix}-0-meal_type": "dinner", f"{prefix}-0-reserved_time": "19:30", f"{prefix}-0-order": "0"}
        bound = MealFormSet(data, instance=self.d2, prefix=prefix)
        self.assertTrue(bound.is_valid(), bound.errors)
        bound.save()
        meal.refresh_from_db()
        self.assertEqual(meal.reserved_time, time(19, 30))
