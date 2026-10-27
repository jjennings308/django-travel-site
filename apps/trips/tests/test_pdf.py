"""The trip booklet PDF (trips:trip_pdf, apps/trips/pdf.py)."""
from datetime import date, datetime, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import (BookingTask, Confirmation, Contact, Day, Lodging, Section, TransportLeg, Trip,
                               TripGrant, TripRole)
from apps.trips.pdf import EMOJI, PdfUnavailable

User = get_user_model()
UTC = dt_timezone.utc


class BookletTests(TestCase):
    def setUp(self):
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Taos", destination="Taos, New Mexico", start_date=date(2026, 9, 12),
                                        end_date=date(2026, 9, 14))
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.day1 = Day.objects.create(trip=self.trip, day_number=1, date=date(2026, 9, 12), theme="Arrival")
        self.day2 = Day.objects.create(trip=self.trip, day_number=2, date=date(2026, 9, 13), theme="High Road")
        Section.objects.create(day=self.day1, section_type="note", title="Tip",
                               content={"tone": "tip", "paragraphs": ["💡 Pickup is in the terminal"]})
        when = datetime(2026, 9, 12, 11, 5, tzinfo=UTC)
        leg = TransportLeg.objects.create(trip=self.trip, mode="plane", operator="DL", service_number="2579",
                                          origin="BWI", destination="ATL", departure_at=when, arrival_at=when,
                                          origin_timezone="America/New_York", destination_timezone="America/New_York")
        Confirmation.objects.create(trip=self.trip, confirmation_number="GCH7JS", provider="Delta").link(leg)
        self.stay = Lodging.objects.create(trip=self.trip, name="Hotel Chimayo", address="125 Washington Ave",
                                           check_in=date(2026, 9, 12), check_out=date(2026, 9, 13))
        Contact.objects.create(trip=self.trip, name="Hertz ABQ", phone="(505) 842-4235")
        BookingTask.objects.create(trip=self.trip, title="Bandelier entry")
        self.url = reverse("trips:trip_pdf", args=[self.trip.pk])

    def test_download_for_anyone_who_can_see_the_trip(self):
        self.client.force_login(self.viewer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="taos-new-mexico-september-12-14-2026-itinerary.pdf"')
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_strangers_get_404(self):
        self.client.force_login(User.objects.create_user("st", "st@example.com", "pw-1234-abcd"))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_booklet_contents(self):
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF-fake"

        self.client.force_login(self.viewer)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake):
            self.client.get(self.url)
        html = captured["html"]
        self.assertIn("Days at a glance", html)
        self.assertIn("Day 1 · Saturday, September 12", html)
        self.assertIn("Check in</span> <strong>Hotel Chimayo</strong>", html)  # the day's stay
        self.assertIn("7:05 AM EDT", html)  # the leg's own local time
        self.assertIn("GCH7JS", html)
        self.assertIn("Hertz ABQ", html)
        self.assertIn("Bandelier entry", html)  # still to book
        self.assertEqual(EMOJI.sub("", "💡 Tip ✈"), " Tip ✈")  # pictographs dropped, symbols kept

    def test_missing_libraries_fall_back_with_a_message(self):
        self.client.force_login(self.viewer)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=PdfUnavailable("no pango")):
            response = self.client.get(self.url, follow=True)
        self.assertRedirects(response, reverse("trips:trip_detail", args=[self.trip.pk]))
        self.assertContains(response, "can&#x27;t be made on this server yet")

    def test_button_on_the_trip_page(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])), self.url)
