"""Edit this day (docs/plans/trip-page-ux.md, U5): the day page is the day's workshop — add
anything to the day from it, see what's on it in timeline order, and come back to the day."""
from datetime import date, datetime, time, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import Day, ItemLink, Meal, Section, TransportLeg, Trip, TripActivity, TripGrant, TripRole

User = get_user_model()
UTC = dt_timezone.utc


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.commentor = User.objects.create_user("co", "co@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 19), end_date=date(2027, 9, 21),
                                        created_by=self.editor)
        for user, role in ((self.editor, TripRole.EDITOR), (self.viewer, TripRole.VIEWER),
                           (self.commentor, TripRole.COMMENTOR)):
            TripGrant.objects.create(trip=self.trip, user=user, role=role)
        self.day = Day.objects.create(trip=self.trip, day_number=2, date=date(2027, 9, 20), theme="Train south")
        self.url = reverse("trips:day_edit", args=[self.trip.pk, self.day.pk])
        self.detail = reverse("trips:trip_detail", args=[self.trip.pk])

    def trip_page(self, user):
        self.client.force_login(user)
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            return self.client.get(self.detail).content.decode()


class LinkAndAccessTests(Fixture):
    def test_edit_this_day_for_editors_only(self):
        self.assertIn(self.url + "?next=", self.trip_page(self.editor))
        self.assertNotIn(self.url + "?next=", self.trip_page(self.viewer))  # (the day's fragment URL starts the same)

    def test_viewers_and_commentors_403_strangers_404(self):
        for user in (self.viewer, self.commentor):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url).status_code, 404)


class AddFromTheDayTests(Fixture):
    def test_each_kind_lands_on_this_day_and_comes_back(self):
        self.client.force_login(self.editor)
        page = self.client.get(self.url).content.decode()
        for href in (reverse("trips:activity_new", args=[self.trip.pk, self.day.pk]),
                     reverse("trips:item_links", args=[self.trip.pk, "day", self.day.pk]),
                     reverse("trips:section_create", args=[self.trip.pk, self.day.pk, "note"]),
                     reverse("trips:leg_quick_add", args=[self.trip.pk, self.day.pk]), 'href="#meals"'):
            self.assertIn(href, page)

        added = self.client.post(reverse("trips:leg_quick_add", args=[self.trip.pk, self.day.pk]), {
            "origin": "Butzbach", "destination": "Frankfurt", "mode": "train", "est_duration": "45 min",
            "next": self.url})
        self.assertRedirects(added, self.url, fetch_redirect_response=False)
        self.assertEqual(TransportLeg.objects.get().date, self.day.date)

        added = self.client.post(reverse("trips:activity_new", args=[self.trip.pk, self.day.pk]) + f"?next={self.url}",
                                 {"kind": "tour", "title": "Fuggerei", "start_time": "11:00"})
        activity = TripActivity.objects.get()
        self.assertEqual(activity.day, self.day)
        self.assertIn(f"next={self.url}", added["Location"].replace("%2F", "/"))  # its page, then back here

        self.client.post(reverse("trips:item_links", args=[self.trip.pk, "day", self.day.pk]), {
            "action": "new_info", "info-title": "Bayern Ticket rules", "return_to": self.url})
        self.assertEqual(ItemLink.objects.get().target, self.day)

        response = self.client.post(reverse("trips:section_create", args=[self.trip.pk, self.day.pk, "note"]),
                                    {"title": "Afternoon stroll", "order": "", "icon": "", "tone": "", "paragraphs": "Old town."})
        self.assertTrue(response["Location"].startswith(self.url))
        self.assertEqual(Section.objects.get().day, self.day)

    def test_on_this_day_follows_the_timeline(self):
        TransportLeg.objects.create(trip=self.trip, mode="train", origin="Frankfurt", destination="Augsburg",
                                    origin_timezone="Europe/Berlin", destination_timezone="Europe/Berlin",
                                    departure_at=datetime(2027, 9, 20, 8, 0, tzinfo=UTC),
                                    arrival_at=datetime(2027, 9, 20, 10, 40, tzinfo=UTC))
        TripActivity.objects.create(trip=self.trip, day=self.day, title="Early tour", start_time=time(9, 0))
        Meal.objects.create(day=self.day, name="Dinner at 7", meal_type="dinner", reserved_time=time(19, 0))
        Meal.objects.create(day=self.day, name="Café idea", meal_type="lunch")
        Section.objects.create(day=self.day, section_type="note", title="Notes", content={"paragraphs": ["x"]})
        self.client.force_login(self.editor)
        html = self.client.get(self.url).content.decode()
        listing = html[html.index('id="on-this-day"'):]
        order = [listing.index(text) for text in ("Early tour", "Frankfurt → Augsburg", "Dinner at 7", "Notes",
                                                   "Café idea")]
        self.assertEqual(order, sorted(order))


class ReturnTests(Fixture):
    def post_day(self, **extra):
        self.client.force_login(self.editor)
        formset = self.client.get(self.url).context["meal_formset"]
        prefix = formset.prefix
        data = {"day_number": "2", "date": "2027-09-20", "theme": "Train south",
                f"{prefix}-TOTAL_FORMS": "0", f"{prefix}-INITIAL_FORMS": "0", f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000", **extra}
        return self.client.post(self.url, data)

    def test_save_returns_to_the_day_on_the_trip_page(self):
        response = self.post_day()
        self.assertRedirects(response, self.detail + "#day-2", fetch_redirect_response=False)

    def test_next_from_edit_trip_is_honoured_and_outside_next_ignored(self):
        edit = reverse("trips:trip_settings", args=[self.trip.pk]) + f"#day-{self.day.pk}"
        self.assertRedirects(self.post_day(next=edit), edit, fetch_redirect_response=False)
        self.assertRedirects(self.post_day(next="https://evil.example.com/"), self.detail + "#day-2",
                             fetch_redirect_response=False)
