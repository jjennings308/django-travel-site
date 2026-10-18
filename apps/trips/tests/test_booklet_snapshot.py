"""The PDF booklet's HTML, pinned (docs/plans/trip-page-ux.md, U1): the web trip page is free to
change; the booklet changes only when a phase says so and the snapshot is updated on purpose.

    UPDATE_SNAPSHOTS=1 python manage.py test apps.trips.tests.test_booklet_snapshot

rewrites ``snapshots/booklet.html``; review the diff before committing it. The HTML is what the
``trip_pdf`` view hands WeasyPrint (``render_pdf`` is mocked), with whitespace collapsed. It
prints no database ids, so it is stable between runs."""
import difflib
import os
import re
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.trips.models import (BookingTask, Confirmation, ConfirmationFile, Contact, Day, ItemLink, Lodging, Meal, Section,
                               TransportLeg, Traveler, Trip, TripActivity, TripGrant, TaskOption, TripInfo, TripRole)

User = get_user_model()
UTC = dt_timezone.utc
SNAPSHOT = Path(__file__).parent / "snapshots" / "booklet.html"


def normalise(html):
    html = re.sub(r">\s+<", "><", html)
    html = re.sub(r"\s+", " ", html)
    return html.replace("><", ">\n<").strip() + "\n"


def build_trip():
    """A small trip with every item kind the booklet prints."""
    trip = Trip.objects.create(name="Snapshot Trip — Europe", destination="Bavaria · Windsor",
                               start_date=date(2027, 9, 17), end_date=date(2027, 9, 20),
                               notes="Overview note.")
    ada = Traveler.objects.create(name="Ada Lovelace")
    bo = Traveler.objects.create(name="Bo Lovelace")
    trip.travelers.set([ada, bo])
    d1 = Day.objects.create(trip=trip, day_number=1, date=date(2027, 9, 17), theme="Overnight flight — PIT → FRA")
    d2 = Day.objects.create(trip=trip, day_number=2, date=date(2027, 9, 18), theme="Arrive — Butzbach",
                            meals_included=True)
    d3 = Day.objects.create(trip=trip, day_number=3, date=date(2027, 9, 19), theme="Marburg day trip")
    d4 = Day.objects.create(trip=trip, day_number=4, date=date(2027, 9, 20), theme="Train south")
    d3.travelers.set([ada])  # a split day

    overnight = TransportLeg.objects.create(
        trip=trip, mode="plane", operator="DL", service_number="0144", origin="PIT", destination="FRA",
        origin_timezone="America/New_York", destination_timezone="Europe/Berlin",
        departure_at=datetime(2027, 9, 17, 22, 30, tzinfo=UTC), arrival_at=datetime(2027, 9, 18, 6, 15, tzinfo=UTC),
        notes="Seats 31A, 31B")
    timed = TransportLeg.objects.create(
        trip=trip, mode="train", operator="DB", service_number="ICE 599", origin="Frankfurt Hbf",
        destination="Augsburg Hbf", origin_timezone="Europe/Berlin", destination_timezone="Europe/Berlin",
        departure_at=datetime(2027, 9, 20, 8, 0, tzinfo=UTC), arrival_at=datetime(2027, 9, 20, 10, 40, tzinfo=UTC))
    travel = Section.objects.create(day=d4, section_type="travel", title="Getting around", order=1,
                                    content={"intro": "Book seats together.", "columns": ["What", "Info"],
                                             "rows": [["Ticket", "Flexpreis"]]})
    planned = TransportLeg.objects.create(trip=trip, mode="train", operator="RE30", origin="Butzbach",
                                          destination="Frankfurt Hbf", date=d4.date, section=travel,
                                          est_duration=timedelta(minutes=45), notes="Frequent service")

    hof = Lodging.objects.create(trip=trip, name="Hotel Hessischer Hof", address="Farbgasse 1, Butzbach",
                                 check_in=d2.date, check_out=d4.date, nightly_rate=Decimal("120.00"), currency="EUR")
    augusta = Lodging.objects.create(trip=trip, name="Hotel Augusta", address="Ludwigstraße 2, Augsburg",
                                     check_in=d4.date, check_out=date(2027, 9, 22))

    Section.objects.create(day=d2, section_type="phase", title="Arrive", order=1,
                           content={"heading": "Morning — Arrive", "summary": "Land FRA, clear customs.",
                                    "highlights": ["Coffee", "Nap"]})
    Section.objects.create(day=d2, section_type="logistics_table", title="Trains", order=2,
                           content={"columns": ["Leg", "Time"], "rows": [["FRA → Butzbach", "~45 min"]]})
    Section.objects.create(day=d2, section_type="callout", title="Tip", order=3,
                           content={"tone": "warning", "text": "💡 Pickup is in the terminal"})
    tour = Section.objects.create(day=d3, section_type="choose_your_adventure", title="Afternoon", order=1,
                                  content={"prompt": "Pick one", "summary": "Both are short.", "options": [
                                      {"letter": "A", "title": "Castle", "description": "Up the hill",
                                       "duration": "2 h", "cost": "€8"},
                                      {"letter": "B", "title": "Old town", "description": "Stroll"}]})
    Section.objects.create(day=d3, section_type="free_text", title="Notes", order=2,
                           content={"paragraphs": ["First paragraph.", "Second paragraph."]})
    dinner = Meal.objects.create(day=d2, name="Ristorante Da Franco", meal_type="dinner", cuisine="Italian",
                                 price_range="$$", why_recommended="Wood-fired pizza",
                                 reservation_notes="Call ahead", reserved_time=time(19, 30))
    Meal.objects.create(day=d3, name="Café Vetter", meal_type="lunch", order=1)

    guide = TripActivity.objects.create(trip=trip, day=d3, kind="tour", title="Student guide", provider="Uni Marburg",
                                        start_time=time(15, 0), end_time=time(16, 30), place_text="Marktplatz",
                                        est_cost=Decimal("40"), currency="EUR", notes="Meet at the fountain")
    guide.travelers.add(ada)
    TripActivity.objects.create(trip=trip, day=d4, kind="entry", title="Fuggerei entry")

    pnr = Confirmation.attach_number(trip, "GCH7JS", overnight, provider="Delta", label="Flights")
    pnr.travelers.add(ada, bo)
    pnr.url = "https://example.com/manage"
    pnr.save()
    db_ticket = Confirmation.attach_number(trip, "DB-1234", timed, provider="Deutsche Bahn")
    # A ticket on it (R5): the booklet names files, never embeds them. No real file is needed.
    ConfirmationFile.objects.create(confirmation=db_ticket, file="trips/snapshot/ticket.pdf",
                                    original_name="DB ticket.pdf", content_type="application/pdf", size=1000)
    Confirmation.attach_number(trip, "5305434791", hof, provider="Booking.com")
    Confirmation.attach_number(trip, "UNI-77", guide, provider="Uni Marburg")
    Confirmation.attach_number(trip, "NIGHT1", tour, provider="Nightwatchman")
    Confirmation.attach_number(trip, "TABLE9", dinner, provider="Da Franco")
    Confirmation.objects.create(trip=trip, confirmation_number="EUSP2592862107", provider="Allianz",
                                label="Travel insurance")

    taxi = Contact.objects.create(trip=trip, name="Taxi Augsburg", role="Taxi", phone="+49 821 35025")
    desk = Contact.objects.create(trip=trip, name="Hotel Hessischer Hof", phone="+49 6033 1234",
                                  email="info@example.com", notes="Front desk 24 h",
                                  address="Farbgasse 1, 35510 Butzbach", url="https://example.com/hof")
    rules = TripInfo.objects.create(trip=trip, title="Bayern Ticket rules",
                                    body="Valid on regional trains only.\n\nUp to 5 people.", url="https://example.com/bt")
    TripInfo.objects.create(trip=trip, title="Currency", body="Cards almost everywhere.")  # linked to nothing
    ItemLink.link(desk, hof)       # on each night of the stay
    ItemLink.link(taxi, planned)   # under a leg
    ItemLink.link(rules, travel)   # a section: the day's Good to know
    ItemLink.link(rules, d2)       # the day itself
    BookingTask.objects.create(trip=trip, title="ICE seats", priority=2, leg=planned, due_note="before Sept 1")
    BookingTask.objects.create(trip=trip, title="Hotel Augusta deposit", priority=1, stay=augusta,
                               due=date(2027, 8, 1))
    BookingTask.objects.create(trip=trip, title="Already done", done=True)
    decide = BookingTask.objects.create(trip=trip, title="Augsburg accommodation", kind="decide", priority=1)
    TaskOption.objects.create(task=decide, title="Hotel Augusta", detail="Old town, 6 rooms", est_cost=Decimal("140"),
                              currency="EUR", url="https://example.com/augusta", order=1, chosen=True)
    TaskOption.objects.create(task=decide, title="Steigenberger Drei Mohren", est_cost=Decimal("210"), currency="EUR",
                              order=2)
    return trip


class BookletSnapshotTests(TestCase):
    def test_booklet_html_matches_the_snapshot(self):
        trip = build_trip()
        user = User.objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        TripGrant.objects.create(trip=trip, user=user, role=TripRole.EDITOR)
        captured = {}

        def fake(html, base_url):
            captured["html"] = html
            return b"%PDF"

        self.client.force_login(user)
        with mock.patch("apps.trips.pdf.render_pdf", side_effect=fake), \
                mock.patch("apps.trips.views.django_timezone.localdate", return_value=date(2027, 8, 15)):
            self.assertEqual(self.client.get(reverse("trips:trip_pdf", args=[trip.pk])).status_code, 200)
        html = normalise(captured["html"])
        if os.environ.get("UPDATE_SNAPSHOTS"):
            SNAPSHOT.write_text(html, encoding="utf-8")
            return
        expected = SNAPSHOT.read_text(encoding="utf-8")
        if html != expected:
            diff = "\n".join(list(difflib.unified_diff(expected.splitlines(), html.splitlines(), "snapshot", "now",
                                                       lineterm=""))[:60])
            self.fail("The booklet's HTML changed. If that's intended, rerun with UPDATE_SNAPSHOTS=1 and review "
                      f"the diff.\n{diff}")
