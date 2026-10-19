"""Rating a finished trip's places (site roadmap R17)."""
import io
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import POI, City, Country
from apps.notifications.models import Notification
from apps.reviews import trip_ratings
from apps.reviews.models import Review, TripRatingPrompt
from apps.trips.models import Day, Traveler, Trip, TripActivity, TripGrant

User = get_user_model()
TODAY = date(2027, 6, 10)


class Fixture(TestCase):
    def setUp(self):
        self.ada = User.objects.create_user("ada", "ada@example.com", "pw-1234-abcd")  # travelled
        self.vi = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")    # followed along
        country = Country.objects.create(name="Italy", slug="italy", iso_code="IT", iso3_code="ITA", continent="EU",
                                         approval_status=ApprovalStatus.APPROVED)
        self.rome = City.objects.create(name="Rome", slug="rome", country=country, latitude=1, longitude=1,
                                        approval_status=ApprovalStatus.APPROVED)
        self.draft = City.objects.create(name="Draftville", slug="draftville", country=country, latitude=1,
                                         longitude=1, approval_status=ApprovalStatus.PENDING)
        self.colosseum = POI.objects.create(name="Colosseum", slug="colosseum", city=self.rome, latitude=1,
                                            longitude=1, approval_status=ApprovalStatus.APPROVED)
        self.trip = Trip.objects.create(name="Rome", start_date=date(2027, 6, 1), end_date=date(2027, 6, 5))
        self.trip.cities.set([self.rome, self.draft])
        day = Day.objects.create(trip=self.trip, day_number=1, date=date(2027, 6, 1), city=self.rome)
        TripActivity.objects.create(trip=self.trip, day=day, title="Tour", poi=self.colosseum, start_time=time(9))
        for user in (self.ada, self.vi):
            TripGrant.objects.create(trip=self.trip, user=user, role="viewer")
        self.trip.travelers.add(Traveler.objects.get(user=self.ada))
        self.url = reverse("reviews:trip_rate", args=[self.trip.pk])

    def prompts(self):
        return Notification.objects.filter(notification_type__name="trip_rating")


class AskTests(Fixture):
    def test_asks_everyone_once_after_the_trip(self):
        self.assertEqual(trip_ratings.ask(today=date(2027, 6, 5)), 0)  # last day: not yet
        self.assertEqual(trip_ratings.ask(today=TODAY), 2)
        self.assertEqual(sorted(n.user.username for n in self.prompts()), ["ada", "vi"])
        self.assertEqual(trip_ratings.ask(today=TODAY + timedelta(days=1)), 0)  # once, ever

    def test_not_for_old_or_deleted_trips_or_inactive_people(self):
        self.assertEqual(trip_ratings.ask(today=date(2027, 8, 1)), 0)  # more than 30 days ago
        User.objects.filter(pk=self.vi.pk).update(is_active=False)
        self.assertEqual(trip_ratings.ask(today=TODAY), 1)
        Trip.objects.filter(pk=self.trip.pk).update(deleted_at=date(2027, 6, 9))
        TripRatingPrompt.objects.all().delete()
        self.assertEqual(trip_ratings.ask(today=TODAY), 0)

    def test_the_daily_digest_run_sends_them(self):
        from unittest import mock
        with mock.patch("apps.reviews.trip_ratings.timezone.localdate", return_value=TODAY):
            out = io.StringIO()
            call_command("send_trip_digests", stdout=out)
        self.assertIn("Sent 2 trip rating prompt(s).", out.getvalue())


class PageTests(Fixture):
    def test_lists_published_cities_and_places(self):
        self.client.force_login(self.ada)
        page = self.client.get(self.url)
        self.assertContains(page, "Rome")
        self.assertContains(page, "Colosseum")
        self.assertNotContains(page, "Draftville")

    def test_saving_makes_and_updates_reviews(self):
        self.client.force_login(self.ada)
        field_city, field_poi = f"city-{self.rome.pk}", f"poi-{self.colosseum.pk}"
        self.client.post(self.url, {f"{field_city}-rating": "5", f"{field_city}-comment": "Loved it"})
        review = Review.objects.get(user=self.ada, location=self.rome)
        self.assertEqual((review.rating, review.comment, review.is_verified_visit), (5, "Loved it", True))
        self.assertFalse(Review.objects.filter(poi=self.colosseum).exists())  # unrated: left alone
        self.client.post(self.url, {f"{field_city}-rating": "4", f"{field_poi}-rating": "3"})
        self.assertEqual(Review.objects.get(user=self.ada, location=self.rome).rating, 4)
        self.assertEqual(Review.objects.filter(user=self.ada).count(), 2)
        self.assertIsNotNone(TripRatingPrompt.objects.get(user=self.ada).answered_at)

    def test_only_travellers_are_marked_been_there(self):
        self.client.force_login(self.vi)
        self.client.post(self.url, {f"city-{self.rome.pk}-rating": "3"})
        self.assertFalse(Review.objects.get(user=self.vi).is_verified_visit)

    def test_skip_and_access(self):
        self.client.force_login(self.vi)
        self.client.post(self.url, {"skip": "1"})
        self.assertIsNotNone(TripRatingPrompt.objects.get(user=self.vi).skipped_at)
        self.assertEqual(trip_ratings.ask(today=TODAY), 1)  # Ada still asked; Vi never again
        stranger = User.objects.create_user("st", "st@example.com", "pw-1234-abcd")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_finished_trip_page_links_here(self):
        from unittest import mock
        self.client.force_login(self.ada)
        with mock.patch("apps.trips.models.django_timezone.localdate", return_value=TODAY):
            page = self.client.get(reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(page, self.url)
