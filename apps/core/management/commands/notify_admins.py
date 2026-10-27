"""Email stdin to ``DJANGO_ADMINS`` (script-emails plan M1; ``apps/core/job_mail.py``): how shell scripts report.

    echo hello | .venv/bin/python manage.py notify_admins --subject test

Always exits 0, even when the mail can't be sent (it says so on stderr): a job must not fail because of its own
report. Nothing is sent while ``DJANGO_ADMINS`` is empty.
"""
import sys

from django.core.management.base import BaseCommand

from apps.core import job_mail


class Command(BaseCommand):
    help = "Email the text on stdin to DJANGO_ADMINS (job reports; exits 0 even when it can't send)."

    def add_arguments(self, parser):
        parser.add_argument("--subject", required=True, help="The subject (prefixed \"[ShareBucketList job]\").")

    def handle(self, *args, subject, **options):
        body = sys.stdin.read() if not sys.stdin.isatty() else ""
        if job_mail.report(subject, body):
            self.stdout.write("Sent to DJANGO_ADMINS.")
        else:
            self.stderr.write("Not sent: DJANGO_ADMINS is empty, or the mail failed (see the log).")
