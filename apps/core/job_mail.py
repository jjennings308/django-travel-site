"""Reports from scripts and scheduled jobs to ``DJANGO_ADMINS`` (script-emails plan M1).

The rule (James, 2026-10-27): anything a script or scheduled job needs to tell James goes to the addresses in
``DJANGO_ADMINS`` (``settings.ADMINS``) — never a per-script address setting or a crontab ``MAILTO``. Web errors
reach the same people through ``core.alerts.AlertEmailHandler``; jobs come through here:

* ``report(subject, body)`` — Python jobs (``check_countries --email``);
* ``manage.py notify_admins --subject …`` (body on stdin) — shell scripts, through ``sbl_notify`` in
  ``scripts/lib/sbl_common.sh`` (``fail()`` and ``scripts/run_job.sh`` call it).

The subject is prefixed ``[ShareBucketList job] `` (not prod's error prefix). Sent from ``SERVER_EMAIL``; nothing is
sent while ``ADMINS`` is empty; a failure to send is logged as a warning and never raised, so a job never fails
because of its own report. Bodies hold counts, step names, file paths and log tails — never secrets, passwords, API
keys or personal data (emails, phones, travel documents).
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)
PREFIX = "[ShareBucketList job] "


def report(subject, body):
    """Email ``body`` to ``ADMINS``; True when it went, False when there was no one to send to or it failed."""
    recipients = list(getattr(settings, "ADMINS", []) or [])
    if not recipients:
        return False
    subject = PREFIX + " ".join(str(subject or "Job report").split())[:150]
    try:
        send_mail(subject, body or "", settings.SERVER_EMAIL, recipients, fail_silently=False)
    except Exception:  # noqa: BLE001 - a report must never take its job down
        log.warning("A job report to DJANGO_ADMINS could not be sent", exc_info=True)
        return False
    return True
