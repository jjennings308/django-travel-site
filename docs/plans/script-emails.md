# Plan: scripts and scheduled jobs email DJANGO_ADMINS

Status: planning only (2026-10-27). Rule set by James 2026-10-27: **any script or scheduled job that needs to
tell James something emails the addresses in `DJANGO_ADMINS`** (Django's `ADMINS`), never a new per-script address
setting or a crontab `MAILTO`. One phase, M1, branch `m1-script-emails`.

## Today

- `check_countries` (country-flags C2) relies on a crontab `MAILTO` line (`scripts/README.md`).
- `backup_prod.sh`, `sync_dev_from_prod.sh` and `sync_staging_from_prod.sh` fail through `fail()` in
  `scripts/lib/sbl_common.sh`, which only writes the log, so a failed backup or sync tells nobody.
- The nightly / daily management commands in James's crontab (`recount_visitors`, `send_trip_digests`,
  `purge_deleted_accounts`, `fetch_rates`, `check_countries`) report only to cron's own mail, if any.
- Only web errors reach `ADMINS` (`apps.core.alerts.AlertEmailHandler`).

## M1 (branch `m1-script-emails`)

1. **One mailer for jobs:** `apps/core/job_mail.py` with `report(subject, body)` → `django.core.mail.mail_admins`
   (subject prefixed `[ShareBucketList job] `, so not the error prefix; `fail_silently=True`, a failure logged as a
   warning; nothing sent when `ADMINS` is empty). Bodies never hold secrets, passwords, API keys or personal data
   (no emails, phones, travel documents) — counts, names of steps, file paths and the tail of the log only.
2. **`manage.py notify_admins --subject "…"`** (in `core`) reads the body from stdin and calls `report()`; exit 0
   even when mail fails (a job must not fail because of its own report). This is how shell scripts reach
   `DJANGO_ADMINS`.
3. **Shell scripts:** `sbl_notify SUBJECT` in `sbl_common.sh` pipes stdin to `"$PY" "$APP/manage.py" notify_admins`
   when the machine has the app (`$APP/manage.py` and its `.venv`), so the same `.env` and mail settings are used.
   `fail()` calls it with the failure line and the last 30 lines of `$LOG`. On a machine without the app
   (popsicletoes.us runs `backup_prod.sh`): read `DJANGO_ADMINS` and `SERVER_EMAIL` with `envval` from that
   machine's `.env` and send with `sendmail -t` if it exists; if neither works, log "could not email DJANGO_ADMINS"
   and carry on. `backup_prod.sh --check` reports which way it will notify (or that it can't). Never add another
   address variable to `.env`.
4. **A wrapper for cron lines:** `scripts/run_job.sh NAME -- command …` runs the command, appends its output to
   `~/logs/sbl-jobs/NAME.log` (keep 60 days), and on a non-zero exit sends one `sbl_notify` ("NAME failed (exit N)"
   + the output's last 30 lines). `--report-on 1` lets a command whose exit 1 means "something to look at" (like
   `check_countries`) mail its whole output on that exit too ("NAME: differences found"), while exit 0 stays quiet.
5. **Management commands that have something to say** call `job_mail.report()` themselves only when it's their
   job to report (none besides `check_countries` today: make it mail its differences via `report()` when run with
   `--email`, and keep printing them). Others just exit non-zero on failure and let `run_job.sh` mail.
6. **Docs:** `scripts/README.md` — drop the `MAILTO` lines; every crontab line goes through `run_job.sh` (list them:
   `recount_visitors`, `send_trip_digests`, `purge_deleted_accounts`, `fetch_rates`, `check_countries --email`,
   `sync_staging_from_prod.sh`), and the systemd timers' services (`deploy/backup/`, `deploy/dev/`) rely on `fail()`.
   `.env.example`: one line by `DJANGO_ADMINS` saying it also receives job reports. CLAUDE.md: the rule (already
   added under "Error emails and health") plus where the pieces are.
7. **Tests** (`apps/core/tests/`): `report()` sends to `ADMINS` with the prefix, sends nothing when `ADMINS` is
   empty, never raises; `notify_admins` reads stdin and exits 0 when mail fails; `run_job.sh` (run from a test like
   `test_backup_scripts` does with `sbl_keep`, with a fake `notify` command on `PATH`) stays quiet on exit 0, reports
   on non-zero, and reports exit 1 only with `--report-on 1`; `fail()` calls `sbl_notify`.

James afterwards: replace the crontab lines with the README's new ones (on tazcomputer and, for the systemd timers,
nothing to change), and send one test with `echo hello | .venv/bin/python manage.py notify_admins --subject test`.
