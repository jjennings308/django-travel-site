"""Time the heavy pages (site roadmap R23): query counts and median milliseconds.

    python manage.py perf_report [--trip <pk>] [--runs 3]

Renders through Django's test client as a staff user inside a transaction that is rolled back, so
nothing is saved (not even the session). Meant for dev's nightly copy of production: run it before and
after a change and compare. The trip is the one given, else the biggest (most days + legs + sections).
"""
import statistics
import time
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Count
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.approval_system.models import ApprovalStatus
from apps.locations.models import City
from apps.trips import calendar
from apps.trips.models import Trip


class Rollback(Exception):
    pass


def biggest_trip():
    return (Trip.objects.live().annotate(size=Count("days", distinct=True) + Count("transport", distinct=True)
                                         + Count("days__sections", distinct=True))
            .order_by("-size", "pk").first())


def measure(fn, runs):
    """(queries on the first run, median ms over ``runs``)."""
    timings, queries = [], None
    for _ in range(runs):
        with CaptureQueriesContext(connection) as ctx:
            start = time.perf_counter()
            fn()
            timings.append((time.perf_counter() - start) * 1000)
        if queries is None:
            queries = len(ctx.captured_queries)
    return queries, statistics.median(timings)


class Command(BaseCommand):
    help = "Query counts and timings for the trip page, booklet, calendar feed and catalogue pages."

    def add_arguments(self, parser):
        parser.add_argument("--trip", type=int, help="Trip id (default: the biggest)")
        parser.add_argument("--runs", type=int, default=3)

    def handle(self, *args, trip=None, runs=3, **options):
        trip = Trip.objects.filter(pk=trip).first() if trip else biggest_trip()
        if trip is None:
            raise CommandError("No trip to time.")
        rows = []
        try:
            with transaction.atomic():
                rows = self._measure(trip, max(1, runs))
                raise Rollback
        except Rollback:
            pass
        self.stdout.write(f"Trip {trip.pk} — {trip.name} ({trip.days.count()} days); median of {runs} run(s)")
        width = max(len(name) for name, *_ in rows)
        self.stdout.write(f"{'page'.ljust(width)}  status  queries      ms")
        for name, status, queries, ms in rows:
            self.stdout.write(f"{name.ljust(width)}  {status:>6}  {queries:>7}  {ms:>6.0f}")

    def _measure(self, trip, runs):
        User = get_user_model()
        staff = User.objects.filter(is_superuser=True, is_active=True).first() or User.objects.create_superuser(
            "perf-report", "perf-report@example.invalid", None)
        staff.accept_legal()  # else every page is the "accept the new terms" redirect (rolled back anyway)
        client = Client(HTTP_HOST="localhost")
        client.force_login(staff)
        city = City.objects.filter(approval_status=ApprovalStatus.APPROVED).annotate(n=Count("pois")).order_by("-n").first()
        today = timezone.localdate()
        pages = [
            ("trip page", reverse("trips:trip_detail", args=[trip.pk])),
            ("settings", reverse("trips:trip_settings", args=[trip.pk])),
            ("bookings", reverse("trips:trip_bookings", args=[trip.pk])),
            ("booklet (HTML only)", ("pdf-html", reverse("trips:trip_pdf", args=[trip.pk]))),
            ("booklet (PDF)", reverse("trips:trip_pdf", args=[trip.pk])),
            ("calendar feed (build)", ("feed", None)),
            ("search ?q=museum", reverse("pages:search") + "?q=museum"),
            ("events calendar", reverse("events:calendar", args=[today.year, today.month])),
            ("sitemap.xml", reverse("sitemap")),
        ]
        if city is not None:
            pages += [("city page", reverse("locations:city_detail", args=[city.slug])),
                      ("city What's on", reverse("events:whats_on", args=["city", city.slug]))]
        rows = []
        for name, target in pages:
            responses = []
            if isinstance(target, tuple) and target[0] == "feed":
                queries, ms = measure(lambda: calendar.build(trip), runs)
                responses.append(None)
            elif isinstance(target, tuple):
                with mock.patch("apps.trips.pdf.render_pdf", return_value=b"%PDF-"):
                    queries, ms = measure(lambda: responses.append(client.get(target[1])), runs)
            else:
                queries, ms = measure(lambda: responses.append(client.get(target)), runs)
            # A 3xx means the timing is of a redirect, not of the page.
            status = responses[-1].status_code if responses[-1] is not None else "-"
            rows.append((name, status, queries, ms))
        return rows
