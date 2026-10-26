"""Stays added and edited from their day (docs/plans/edit-by-day.md, E1)."""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City, Country
from apps.trips.models import Confirmation, Day, Lodging, Trip, TripChange, TripGrant, TripRole

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        de = Country.objects.create(name="Germany", slug="de", iso_code="DE", iso3_code="DEU", continent="Europe",
                                    approval_status=ApprovalStatus.APPROVED)
        self.augsburg = City.objects.create(name="Augsburg", slug="augsburg", country=de, latitude=48.37,
                                            longitude=10.9, approval_status=ApprovalStatus.APPROVED)
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 20), end_date=date(2027, 9, 24),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.trip.cities.add(self.augsburg)
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 19 + n),
                                        city=self.augsburg if n == 1 else None) for n in range(1, 5)]
        self.new_url = reverse("trips:stay_new", args=[self.trip.pk, self.days[0].pk])

    def data(self, **over):
        values = {"name": "Hotel Augusta", "address": "", "city": self.augsburg.pk, "latitude": "", "longitude": "",
                  "check_in": "2027-09-20", "check_out": "2027-09-23", "nightly_rate": "", "currency": "EUR",
                  "notes": ""}
        values.update(over)
        return values

    def stay(self, **over):
        values = {"trip": self.trip, "name": "Hotel Augusta", "check_in": date(2027, 9, 20),
                  "check_out": date(2027, 9, 23), "city": self.augsburg}
        values.update(over)
        return Lodging.objects.create(**values)


class NewStayTests(Fixture):
    def test_starts_on_its_day_for_one_night_in_the_days_city(self):
        self.client.force_login(self.editor)
        form = self.client.get(self.new_url).context["form"]
        self.assertEqual((form.initial["check_in"], form.initial["check_out"], form.initial["city"]),
                         (date(2027, 9, 20), date(2027, 9, 21), self.augsburg.pk))

    def test_saving_lands_on_its_own_page_and_records_who_added_it(self):
        self.client.force_login(self.editor)
        response = self.client.post(self.new_url, self.data())
        stay = Lodging.objects.get()
        self.assertTrue(response["Location"].startswith(reverse("trips:stay_edit", args=[self.trip.pk, stay.pk])))
        self.assertIn("next=", response["Location"])  # and returns to the day after that
        added = TripChange.objects.filter(kind="added", summary__contains="Hotel Augusta")
        self.assertEqual([change.actor for change in added], [self.editor])  # the day fixtures were added by nobody

    def test_fills_the_days_it_covers_with_its_city(self):
        self.client.force_login(self.editor)
        response = self.client.post(self.new_url, self.data(), follow=True)
        self.assertEqual(list(Day.objects.filter(trip=self.trip, city=self.augsburg).values_list("day_number", flat=True)),
                         [1, 2, 3])  # check-in up to, not including, check-out
        self.assertContains(response, "Filled in the city for 2 days from this stay")

    @mock.patch("apps.core.geocoding.geocode", return_value=(48.369, 10.898))
    def test_the_address_is_looked_up_once(self, geocode):
        self.client.force_login(self.editor)
        self.client.post(self.new_url, self.data(address="Maximilianstr. 1, Augsburg"))
        stay = Lodging.objects.get()
        self.assertEqual(geocode.call_count, 1)
        self.assertEqual((float(stay.latitude), float(stay.longitude)), (48.369, 10.898))
        self.client.post(reverse("trips:stay_edit", args=[self.trip.pk, stay.pk]),
                         self.data(address="Maximilianstr. 1, Augsburg", latitude="48.369", longitude="10.898",
                                   notes="Quiet room"))
        self.assertEqual(geocode.call_count, 1)  # same address: not looked up again

    def test_no_address_means_no_pin_is_copied_from_the_city(self):
        self.client.force_login(self.editor)
        self.client.post(self.new_url, self.data())
        stay = Lodging.objects.get()
        self.assertEqual((stay.latitude, stay.longitude), (None, None))
        self.assertEqual([float(v) for v in stay.map_position], [48.37, 10.9])  # the map's fallback: the city's centre


class StayPageTests(Fixture):
    def test_details_pin_fold_confirmations_and_contacts(self):
        stay = self.stay()
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:stay_edit", args=[self.trip.pk, stay.pk])).content.decode()
        fold = html[html.index("data-adjust-pin"):html.index("</details>", html.index("data-adjust-pin"))]
        self.assertIn('name="latitude"', fold)
        self.assertIn("Found from the address. Without an address the map uses the city", fold)
        self.assertEqual(html.count('name="latitude"'), 1)
        self.assertIn(reverse("trips:item_confirmations", args=[self.trip.pk, "stay", stay.pk]), html)
        self.assertIn(reverse("trips:item_links", args=[self.trip.pk, "stay", stay.pk]), html)

    def test_saving_goes_back_to_next_only_when_it_is_on_this_site(self):
        stay = self.stay()
        url = reverse("trips:stay_edit", args=[self.trip.pk, stay.pk])
        self.client.force_login(self.editor)
        response = self.client.post(url, {**self.data(name="Augusta"), "next": "/trips/"})
        self.assertEqual(response["Location"], "/trips/")
        response = self.client.post(url, {**self.data(), "next": "https://evil.example/"})
        self.assertEqual(response["Location"],
                         reverse("trips:day_edit", args=[self.trip.pk, self.days[0].pk]) + "#on-this-day")

    def test_delete_keeps_the_confirmation(self):
        stay = self.stay()
        confirmation = Confirmation.attach_number(self.trip, "AUG-1", stay)
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:stay_delete", args=[self.trip.pk, stay.pk]))
        self.assertFalse(Lodging.objects.exists())
        self.assertTrue(Confirmation.objects.filter(pk=confirmation.pk).exists())

    def test_viewer_403_stranger_404(self):
        stay = self.stay()
        urls = [self.new_url, reverse("trips:stay_edit", args=[self.trip.pk, stay.pk]),
                reverse("trips:stay_delete", args=[self.trip.pk, stay.pk])]
        for user, status in ((self.viewer, 403), (self.stranger, 404)):
            self.client.force_login(user)
            for url in urls:
                with self.subTest(user=user.username, url=url):
                    self.assertEqual(self.client.get(url).status_code, status)
        other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        theirs = Lodging.objects.create(trip=other, name="x", check_in=date(2027, 1, 1), check_out=date(2027, 1, 2))
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("trips:stay_edit", args=[self.trip.pk, theirs.pk])).status_code, 404)


class DayAndTripPageTests(Fixture):
    def test_day_page_adds_and_lists_stays(self):
        stay = self.stay()
        self.client.force_login(self.editor)
        rows = {}
        for day in self.days:
            html = self.client.get(reverse("trips:day_edit", args=[self.trip.pk, day.pk])).content.decode()
            on_this_day = html[html.index('id="on-this-day"'):]
            rows[day.day_number] = (stay.name in on_this_day,
                                    next((label for label in ("Check in", "Sleeping", "Check out") if label in on_this_day), None))
        self.assertEqual(rows, {1: (True, "Check in"), 2: (True, "Sleeping"), 3: (True, "Sleeping"),
                                4: (True, "Check out")})
        html = self.client.get(reverse("trips:day_edit", args=[self.trip.pk, self.days[0].pk])).content.decode()
        self.assertIn(f'href="{self.new_url}?next=', html)  # + Stay
        self.assertIn(reverse("trips:stay_edit", args=[self.trip.pk, stay.pk]) + "?next=", html)

    def test_trip_page_stay_card_links_editors_to_its_page(self):
        stay = self.stay()
        edit = reverse("trips:stay_edit", args=[self.trip.pk, stay.pk])
        self.client.force_login(self.editor)
        html = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()
        self.assertIn(f'href="{edit}?next=', html)
        self.assertIn(f"%23stay-{stay.pk}", html)
        self.client.force_login(self.viewer)
        self.assertNotIn(edit, self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode())
