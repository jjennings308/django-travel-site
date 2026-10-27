"""Scripts and scheduled jobs email DJANGO_ADMINS (docs/plans/script-emails.md, M1): ``job_mail.report``,
``manage.py notify_admins``, ``sbl_notify`` / ``fail()`` in ``scripts/lib/sbl_common.sh`` and ``scripts/run_job.sh``.

The shell parts run against a fake app (a ``manage.py`` and a ``.venv/bin/python`` that records what it was asked
to send) or a fake ``sendmail`` on PATH, so nothing is mailed and nothing outside a temporary folder is touched."""
import io
import os
import shutil
import stat
import subprocess
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from apps.core import job_mail

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
ADMINS = ["James <james@example.com>"]


@override_settings(ADMINS=ADMINS, SERVER_EMAIL="alerts@example.com")
class ReportTests(TestCase):
    def test_sends_to_admins_with_the_job_prefix(self):
        self.assertTrue(job_mail.report("Backup  failed", "Last lines…"))
        message, = mail.outbox
        self.assertEqual((message.subject, message.to, message.from_email, message.body),
                         ("[ShareBucketList job] Backup failed", ADMINS, "alerts@example.com", "Last lines…"))

    @override_settings(ADMINS=[])
    def test_nobody_to_send_to(self):
        self.assertFalse(job_mail.report("x", "y"))
        self.assertEqual(mail.outbox, [])

    def test_never_raises(self):
        with mock.patch("apps.core.job_mail.send_mail", side_effect=OSError("SMTP down")):
            with self.assertLogs("apps.core.job_mail", "WARNING"):
                self.assertFalse(job_mail.report("x", "y"))

    def test_notify_admins_reads_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("line one\nline two\n")):
            call_command("notify_admins", "--subject", "sync failed", stdout=StringIO(), stderr=StringIO())
        self.assertEqual((mail.outbox[0].subject, mail.outbox[0].body),
                         ("[ShareBucketList job] sync failed", "line one\nline two\n"))

    def test_notify_admins_exits_0_when_mail_fails(self):
        err = StringIO()
        with mock.patch("apps.core.job_mail.send_mail", side_effect=OSError("SMTP down")), \
                mock.patch("sys.stdin", io.StringIO("x")), self.assertLogs("apps.core.job_mail", "WARNING"):
            call_command("notify_admins", "--subject", "s", stdout=StringIO(), stderr=err)  # no SystemExit
        self.assertIn("Not sent", err.getvalue())


class ShellFixture(SimpleTestCase):
    """A temporary fake app: ``manage.py`` and a ``.venv/bin/python`` that writes its arguments and stdin to
    ``sent.txt`` (one block per call), so ``sbl_notify`` can be watched without mailing anyone."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sbl-test-jobmail-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app = self.tmp / "app"
        (self.app / ".venv" / "bin").mkdir(parents=True)
        (self.app / "manage.py").write_text("# fake\n")
        python = self.app / ".venv" / "bin" / "python"
        python.write_text(f'#!/usr/bin/env bash\n{{ echo "ARGS: $*"; echo "SETTINGS: ${{DJANGO_SETTINGS_MODULE:-}}"; '
                          f'cat; echo "--"; }} >> "{self.tmp}/sent.txt"\n')
        python.chmod(python.stat().st_mode | stat.S_IEXEC)
        self.logs = self.tmp / "logs"

    def sent(self):
        path = self.tmp / "sent.txt"
        return path.read_text() if path.exists() else ""

    def run_job(self, *args):
        env = {**os.environ, "SBL_APP": str(self.app), "SBL_JOB_LOGS": str(self.logs)}
        return subprocess.run(["bash", str(SCRIPTS / "run_job.sh"), *args], capture_output=True, text=True, env=env)


class RunJobTests(ShellFixture):
    def test_quiet_on_success_and_keeps_the_output(self):
        result = self.run_job("recount", "--", "bash", "-c", "echo counted 12")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.sent(), "")
        log, = (self.logs / "recount").glob("*.log")
        self.assertIn("counted 12", log.read_text())

    def test_a_failure_is_reported_with_the_last_lines(self):
        result = self.run_job("digests", "--", "bash", "-c", "echo step one; echo boom >&2; exit 3")
        self.assertEqual(result.returncode, 3)
        sent = self.sent()
        self.assertIn("ARGS: manage.py notify_admins --subject digests failed (exit 3)", sent)
        self.assertIn("boom", sent)
        self.assertIn("step one", sent)

    def test_exit_1_is_a_failure_unless_report_on_1(self):
        self.run_job("check", "--", "bash", "-c", "echo ZW differs; exit 1")
        self.assertIn("check failed (exit 1)", self.sent())
        (self.tmp / "sent.txt").unlink()
        result = self.run_job("check", "--report-on", "1", "--", "bash", "-c", "echo ZW differs; exit 1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--subject check: something to look at (exit 1)", self.sent())
        self.assertIn("ZW differs", self.sent())
        (self.tmp / "sent.txt").unlink()
        self.run_job("check", "--report-on", "1", "--", "bash", "-c", "exit 0")
        self.assertEqual(self.sent(), "")

    def test_the_settings_reach_the_report(self):
        env = {**os.environ, "SBL_APP": str(self.app), "SBL_JOB_LOGS": str(self.logs),
               "DJANGO_SETTINGS_MODULE": "config.settings.prod"}
        subprocess.run(["bash", str(SCRIPTS / "run_job.sh"), "x", "--", "false"], env=env, capture_output=True)
        self.assertIn("SETTINGS: config.settings.prod", self.sent())

    def test_bad_usage(self):
        self.assertEqual(self.run_job("only-a-name").returncode, 64)
        self.assertEqual(self.run_job("x", "no-dashes", "true").returncode, 64)


class FailTests(ShellFixture):
    def run_bash(self, script, path=None):
        env = {**os.environ, "APP": str(self.app), "LOG": str(self.tmp / "script.log")}
        if path is not None:
            env["PATH"] = path
        return subprocess.run(["bash", "-c", f'. "{SCRIPTS / "lib" / "sbl_common.sh"}"; {script}'],
                              capture_output=True, text=True, env=env)

    def test_fail_emails_the_log_tail_and_exits_1(self):
        (self.tmp / "script.log").write_text("earlier line\n")
        result = self.run_bash('fail "could not dump production"')
        self.assertEqual(result.returncode, 1)
        sent = self.sent()
        self.assertIn("--subject bash failed", sent)
        self.assertIn("FAILED: could not dump production", sent)
        self.assertIn("earlier line", sent)

    def test_without_the_app_sendmail_with_the_env_addresses(self):
        shutil.rmtree(self.app / ".venv")
        (self.app / ".env").write_text('DJANGO_ADMINS="James <james@example.com>"\nSERVER_EMAIL=alerts@example.com\n')
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        sendmail = bin_dir / "sendmail"
        sendmail.write_text(f'#!/usr/bin/env bash\necho "SENDMAIL $*" >> "{self.tmp}/sent.txt"; cat >> "{self.tmp}/sent.txt"\n')
        sendmail.chmod(sendmail.stat().st_mode | stat.S_IEXEC)
        result = self.run_bash('echo "backup broke" | sbl_notify "backup failed"; sbl_notify_how',
                               path=f"{bin_dir}:{os.environ['PATH']}")
        self.assertEqual(result.stdout.strip().splitlines()[-1], "sendmail")
        sent = self.sent()
        self.assertIn("SENDMAIL -t", sent)
        self.assertIn("To: James <james@example.com>", sent)
        self.assertIn("From: alerts@example.com", sent)
        self.assertIn("Subject: [ShareBucketList job] backup failed", sent)
        self.assertIn("backup broke", sent)

    def test_no_way_to_mail_logs_a_line_and_carries_on(self):
        shutil.rmtree(self.app / ".venv")
        result = self.run_bash('echo x | sbl_notify "s"; echo "status $?"', path="/usr/bin:/bin")
        self.assertIn("status 0", result.stdout)
        self.assertIn("could not email DJANGO_ADMINS (s)", (self.tmp / "script.log").read_text())


class SyntaxTests(SimpleTestCase):
    def test_run_job_parses(self):
        result = subprocess.run(["bash", "-n", str(SCRIPTS / "run_job.sh")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
