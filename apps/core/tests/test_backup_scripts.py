"""The backup scripts (site roadmap R2): they parse, and the retention rule keeps the right days.

The scripts themselves talk to production and Docker, so they are run by hand (see
scripts/README.md); what can go quietly wrong without either — a syntax slip, or pruning
the wrong backups — is pinned here.
"""
import subprocess
from datetime import date, timedelta
from pathlib import Path

from django.test import SimpleTestCase

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"


def keep(dates, daily=14, weekly=8, monthly=12):
    script = f'. "{SCRIPTS / "lib" / "sbl_common.sh"}"; sbl_keep {daily} {weekly} {monthly}'
    out = subprocess.run(["bash", "-c", script], input="\n".join(dates), capture_output=True, text=True, check=True)
    return out.stdout.split()


def days_back(n, end=date(2026, 10, 18)):
    return [(end - timedelta(days=i)).isoformat() for i in range(n)]


class ScriptSyntaxTests(SimpleTestCase):
    def test_scripts_parse(self):
        for name in ("backup_prod.sh", "restore_check.sh", "sync_dev_from_prod.sh", "lib/sbl_common.sh"):
            with self.subTest(script=name):
                result = subprocess.run(["bash", "-n", str(SCRIPTS / name)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


class RetentionTests(SimpleTestCase):
    def test_a_short_history_is_kept_whole(self):
        self.assertEqual(sorted(keep(days_back(10))), sorted(days_back(10)))

    def test_fourteen_daily_eight_weekly_twelve_monthly(self):
        kept = keep(days_back(800))
        self.assertTrue(set(days_back(14)) <= set(kept))
        # Weekly: the newest backup in each of the 8 most recent ISO weeks (Sundays here).
        for sunday in ("2026-10-04", "2026-09-27", "2026-09-20", "2026-09-13", "2026-09-06"):
            self.assertIn(sunday, kept)
        self.assertNotIn("2026-08-23", kept)  # the 9th week back
        # Monthly: the newest in each of the 12 most recent months.
        for month_end in ("2026-09-30", "2026-08-31", "2026-02-28", "2025-11-30"):
            self.assertIn(month_end, kept)
        self.assertNotIn("2025-10-31", kept)  # the 13th month back
        self.assertEqual(len(kept), 31)

    def test_gaps_keep_the_newest_in_each_period(self):
        # A machine that was off: whatever exists in a month still counts for that month.
        dates = days_back(14) + ["2026-08-05", "2026-08-04", "2026-06-15"]  # Wed and Tue of one week
        kept = keep(dates)
        self.assertIn("2026-08-05", kept)
        self.assertNotIn("2026-08-04", kept)
        self.assertIn("2026-06-15", kept)

    def test_other_names_are_ignored(self):
        self.assertEqual(keep(["2026-10-18", "notes.txt", ".2026-10-17.dump.partial"]), ["2026-10-18"])
