"""Performance and dependency upkeep (site roadmap R23)."""
import re
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.trips.models import BookingTask, Contact, Day, Lodging, TransportLeg, Trip, TripGrant

ROOT = Path(settings.BASE_DIR)
FLOATING = re.compile(r"@(latest|\d+\.x(\.x)?|\d+)(/|$)")


def template_files():
    yield from (ROOT / "templates").rglob("*.html")
    yield from (ROOT / "apps").glob("*/templates/**/*.html")


class CdnTests(TestCase):
    def test_every_cdn_script_and_stylesheet_is_pinned_with_sri(self):
        checked = 0
        for path in template_files():
            text = path.read_text()
            for tag in re.findall(r"<(?:script|link)\b[^>]*>", text):
                url = re.search(r'(?:src|href)="(https?://[^"]+)"', tag)
                if not url or (tag.startswith("<link") and 'stylesheet' not in tag):
                    continue
                if "{%" in url.group(1):
                    continue
                checked += 1
                where = f"{path.relative_to(ROOT)}: {url.group(1)}"
                self.assertIn('integrity="sha', tag, where)
                self.assertIn('crossorigin="anonymous"', tag, where)
                self.assertIsNone(FLOATING.search(url.group(1)), f"floating version in {where}")
        self.assertGreaterEqual(checked, 8)

    def test_offline_cache_name_matches_the_worker(self):
        worker = (ROOT / "apps/core/static/core/sw.js").read_text()
        page = (ROOT / "apps/trips/templates/trips/partials/_offline.html").read_text()
        prefix = re.search(r'const CACHE = "(sbl-offline-[^"]*)"', worker).group(1)
        self.assertIn(f'var CACHE = "{prefix}{{{{ offline_key }}}}"', page)


class CiTests(TestCase):
    def test_ci_audits_dependencies_and_runs_on_pull_requests(self):
        workflow = (ROOT / ".github/workflows/test.yml").read_text()
        self.assertIn("pip-audit -r requirements.txt", workflow)
        self.assertIn(".pip-audit-ignore", workflow)
        self.assertRegex(workflow, r"pull_request:\s*\n\s*branches: \[main\]")
        self.assertTrue((ROOT / ".pip-audit-ignore").exists())

    def test_dependabot_monthly_for_pip_and_actions(self):
        config = (ROOT / ".github/dependabot.yml").read_text()
        for ecosystem in ("pip", "github-actions"):
            self.assertRegex(config, rf"package-ecosystem: {ecosystem}\s*\n\s*directory: \"/\"\s*\n\s*schedule:\s*\n\s*interval: monthly")


class PerfReportTests(TestCase):
    def test_reports_every_page_and_saves_nothing(self):
        trip = Trip.objects.create(name="Tiny", start_date=date(2027, 5, 1), end_date=date(2027, 5, 2))
        Day.objects.create(trip=trip, day_number=1, date=date(2027, 5, 1))
        users_before = get_user_model().objects.count()
        out = StringIO()
        call_command("perf_report", trip=trip.pk, runs=1, stdout=out)
        report = out.getvalue()
        for name in ("trip page", "edit trip", "booklet (HTML only)", "calendar feed", "search", "sitemap.xml"):
            self.assertIn(name, report)
        self.assertNotRegex(report, r"\s3\d\d\s")  # no redirect was timed
        self.assertEqual(get_user_model().objects.count(), users_before)  # rolled back


class EditTripQueryTests(TestCase):
    """Edit trip's formsets share their select options (R23): the query count doesn't grow with rows."""

    def setUp(self):
        self.editor = get_user_model().objects.create_user("ed", "ed@example.com", "pw-1234-abcd")
        self.trip = Trip.objects.create(name="Big", start_date=date(2027, 5, 1), end_date=date(2027, 5, 20),
                                        created_by=self.editor)
        TripGrant.objects.create(trip=self.trip, user=self.editor, role="editor")
        self.client.force_login(self.editor)
        self.add(1)

    def add(self, n):
        start = self.trip.days.count()
        for i in range(start, start + n):
            day = Day.objects.create(trip=self.trip, day_number=i + 1, date=date(2027, 5, 1) + timedelta(days=i))
            TransportLeg.objects.create(trip=self.trip, date=day.date, origin=f"A{i}", destination=f"B{i}")
            Lodging.objects.create(trip=self.trip, name=f"Inn {i}", check_in=day.date,
                                   check_out=day.date + timedelta(days=1))
            BookingTask.objects.create(trip=self.trip, title=f"Book {i}", day=day)
            Contact.objects.create(trip=self.trip, name=f"Guide {i}")

    def count(self):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse("trips:trip_edit", args=[self.trip.pk]))
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_fixed_query_count(self):
        self.count()  # warm Django's content-type cache, as test_detail's QueryCountTests does
        before = self.count()
        self.add(6)
        self.assertEqual(self.count(), before)
