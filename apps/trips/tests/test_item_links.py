"""Contacts and info notes linked to items (docs/plans/trip-page-ux.md, U4): ItemLink, where they
show on the web and in the booklet, editing, and the privacy audit."""
from datetime import date, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import (Contact, Day, ItemLink, Lodging, Section, TransportLeg, Trip, TripGrant, TripInfo,
                               TripRole)

User = get_user_model()


class Fixture(TestCase):
    def setUp(self):
        self.editor = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.viewer = User.objects.create_user("vi", "vi@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Europe", start_date=date(2027, 9, 26), end_date=date(2027, 9, 29),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role=TripRole.EDITOR)
        TripGrant.objects.create(trip=self.trip, user=self.viewer, role=TripRole.VIEWER)
        self.days = [Day.objects.create(trip=self.trip, day_number=n, date=date(2027, 9, 25 + n)) for n in range(1, 5)]
        self.hotel = Lodging.objects.create(trip=self.trip, name="Hard Days Night Hotel", check_in=self.days[0].date,
                                            check_out=self.days[3].date)
        self.leg = TransportLeg.objects.create(trip=self.trip, mode="train", origin="Augsburg", destination="Munich",
                                               date=self.days[1].date, est_duration=timedelta(minutes=35))
        self.section = Section.objects.create(day=self.days[1], section_type="free_text", title="Oktoberfest",
                                              content={"paragraphs": ["Tents open at 10."]})
        self.desk = Contact.objects.create(trip=self.trip, name="Front desk", role="Hotel", phone="+44 151 236 1964",
                                           email="desk@example.com")
        self.rules = TripInfo.objects.create(trip=self.trip, title="Bayern Ticket rules", body="Regional trains only.")
        self.other = Trip.objects.create(name="Other", start_date=date(2027, 1, 1), end_date=date(2027, 1, 2))
        self.other_day = Day.objects.create(trip=self.other, day_number=1, date=date(2027, 1, 1))

    def page(self, user=None):
        self.client.force_login(user or self.viewer)
        with mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 9, 1)):
            return self.client.get(reverse("trips:trip_detail", args=[self.trip.pk])).content.decode()

    def day_html(self, html, number):
        start = html.index(f'id="day-{number}"')
        end = html.find(f'id="day-{number + 1}"', start)
        return html[start:end if end != -1 else html.index('id="reference"')]


class ModelTests(Fixture):
    def test_link_checks_the_trip_and_is_once_per_pair(self):
        ItemLink.link(self.desk, self.hotel)
        ItemLink.link(self.desk, self.hotel)
        self.assertEqual(ItemLink.objects.count(), 1)
        with self.assertRaises(ValueError):
            ItemLink.link(self.desk, self.other_day)

    def test_unlinking_never_deletes_and_deleting_either_end_removes_links(self):
        ItemLink.link(self.desk, self.leg)
        ItemLink.link(self.rules, self.leg)
        ItemLink.link(self.rules, self.section)
        ItemLink.unlink(self.desk, self.leg)
        self.assertTrue(Contact.objects.filter(pk=self.desk.pk).exists())
        self.leg.delete()
        self.assertEqual(ItemLink.objects.count(), 1)  # the section's
        self.rules.delete()
        self.assertFalse(ItemLink.objects.exists())
        self.assertTrue(Section.objects.filter(pk=self.section.pk).exists())


class WebTests(Fixture):
    def test_a_contact_on_a_stay_shows_every_night_and_once_in_reference(self):
        ItemLink.link(self.desk, self.hotel)
        html = self.page()
        for number in (1, 2, 3):
            self.assertIn("Front desk", self.day_html(html, number))
        self.assertNotIn("Front desk", self.day_html(html, 4))  # check-out morning: no night there
        reference = html[html.index('id="reference"'):]
        self.assertEqual(reference.count(f'id="contact-{self.desk.pk}"'), 1)
        self.assertIn('href="tel:+441512361964"', html)
        self.assertIn('href="mailto:desk@example.com"', html)
        self.assertIn("On: <a", reference)

    def test_info_under_a_leg_and_in_good_to_know(self):
        ItemLink.link(self.rules, self.leg)
        ItemLink.link(self.rules, self.days[2])
        html = self.page()
        leg_row = html[html.index(f'id="leg-{self.leg.pk}"'):]
        self.assertIn("Bayern Ticket rules", leg_row[:3000])
        self.assertIn("Good to know", self.day_html(html, 3))
        self.assertIn(f'id="info-{self.rules.pk}"', html[html.index('id="reference"'):])

    def test_in_the_booklet_on_its_day_and_in_reference(self):
        ItemLink.link(self.rules, self.leg)
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF"

        self.client.force_login(self.viewer)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake):
            self.client.get(reverse("trips:trip_pdf", args=[self.trip.pk]))
        html = captured["html"]
        self.assertEqual(html.count("Bayern Ticket rules"), 2)  # under the leg on Day 2, and in Info
        self.assertIn("<h3>Info</h3>", html)


class EditingTests(Fixture):
    def url(self, kind, item):
        return reverse("trips:item_links", args=[self.trip.pk, kind, item.pk])

    def test_attach_create_and_remove_from_an_item(self):
        self.client.force_login(self.editor)
        self.client.post(self.url("leg", self.leg), {"action": "attach", "source": f"contact:{self.desk.pk}"})
        self.client.post(self.url("stay", self.hotel), {"action": "new_contact", "contact-name": "Taxi",
                                                        "contact-phone": "+44 151 222"})
        self.client.post(self.url("day", self.days[1]), {"action": "new_info", "info-title": "Tent guide",
                                                         "info-body": "Arrive early."})
        self.assertEqual(ItemLink.objects.count(), 3)
        taxi = Contact.objects.get(name="Taxi")
        self.client.post(self.url("stay", self.hotel), {"action": "detach", "source": f"contact:{taxi.pk}"})
        self.assertEqual(ItemLink.objects.count(), 2)
        self.assertTrue(Contact.objects.filter(pk=taxi.pk).exists())

    def test_refuses_other_trips_and_checks_permissions(self):
        self.client.force_login(self.editor)
        self.assertEqual(self.client.get(reverse("trips:item_links",
                                                 args=[self.trip.pk, "day", self.other_day.pk])).status_code, 404)
        theirs = Contact.objects.create(trip=self.other, name="Theirs")
        self.assertEqual(self.client.post(self.url("leg", self.leg), {"action": "attach",
                                                                      "source": f"contact:{theirs.pk}"}).status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url("leg", self.leg)).status_code, 403)

    def test_contact_and_info_pages_save_their_ticks(self):
        self.client.force_login(self.editor)
        self.client.post(reverse("trips:contact_edit", args=[self.trip.pk, self.desk.pk]), {
            "name": "Front desk", "phone": "+44 151 236 1964", "address": "Mathew St, Liverpool",
            "links": [f"stay:{self.hotel.pk}", f"leg:{self.leg.pk}"]})
        self.desk.refresh_from_db()
        self.assertEqual((self.desk.address, self.desk.item_links.count()), ("Mathew St, Liverpool", 2))
        self.client.post(reverse("trips:contact_edit", args=[self.trip.pk, self.desk.pk]), {
            "name": "Front desk", "links": [f"stay:{self.hotel.pk}"]})
        self.assertEqual(self.desk.item_links.count(), 1)
        self.client.post(reverse("trips:info_new", args=[self.trip.pk]), {
            "title": "Currency", "body": "Cards everywhere.", "links": [f"section:{self.section.pk}"]})
        self.assertEqual(TripInfo.objects.get(title="Currency").item_links.count(), 1)
        self.assertNotIn(f"day:{self.other_day.pk}", self.client.get(
            reverse("trips:info_new", args=[self.trip.pk])).content.decode())


class AuditTests(Fixture):
    def test_a_contact_phone_in_the_public_view_is_caught(self):
        self.trip.enable_public()
        with self.assertRaises(SystemExit) as clean:
            call_command("audit_public_leak", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(clean.exception.code, 0)
        self.trip.destination = "Liverpool +44 151 236 1964"
        self.trip.save()
        with self.assertRaises(SystemExit) as caught:
            call_command("audit_public_leak", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(caught.exception.code, 1)
