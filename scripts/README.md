# Project Scripts

## reset_db.sh
Safely drops and recreates the local Docker Postgres database.

Usage:

set -a; source .env; set +a
./scripts/reset_db.sh
python manage.py migrate


**WARNING:** This deletes all data in the configured database.

## Production backups (backup_prod.sh, on popsicletoes.us)

`backup_prod.sh` copies production onto the backup machine every night, and only ever reads
production. It writes:

- `~/backups/sharebucketlist/db/YYYY-MM-DD.dump`: the database (`pg_dump -Fc`), checked
  before it is kept;
- `~/backups/sharebucketlist/files/YYYY-MM-DD/`: `uploads/` and `private_uploads/`. Files that
  didn't change share disk space with the day before (hard links), so every day is a full copy.

It keeps 14 daily, 8 weekly and 12 monthly backups, and writes one line per run to
`~/backups/sharebucketlist/backup.log`. A failed run exits 1, deletes nothing, and shows as
failed in `systemctl --user status sbl-backup`.

**Set up once on popsicletoes.us:**

```bash
sudo apt install rsync postgresql-client-17           # pg_restore must be 17 or newer
ssh-keygen -t ed25519                                  # if ~/.ssh has no key yet
ssh-copy-id james@tazcomputer.com                      # lets the backup log in to production
git clone git@github.com:jjennings308/django-travel-site.git ~/projects/travel_site
bash ~/projects/travel_site/scripts/backup_prod.sh --check     # every line should say ok; changes nothing
bash ~/projects/travel_site/scripts/backup_prod.sh             # the first backup, now
cp ~/projects/travel_site/deploy/backup/sbl-backup.* ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now sbl-backup.timer
loginctl enable-linger $USER                           # so it runs while logged out
```

The clone only provides the scripts; it needs no virtualenv or `.env`. Run `git pull` there
when the scripts change.

**Checking on it:** `tail ~/backups/sharebucketlist/backup.log`,
`systemctl --user list-timers sbl-backup.timer`, `journalctl --user -u sbl-backup`.

## Restore drill (restore_check.sh, monthly, on the dev machine)

It proves a backup can be restored. It needs Docker and the repo's `.venv`, so run it on the dev
machine (use whatever name reaches the backup machine from there):

```bash
scp popsicletoes.us:backups/sharebucketlist/db/$(date +%F).dump ~/db_backups/drill.dump
bash scripts/restore_check.sh ~/db_backups/drill.dump && rm ~/db_backups/drill.dump
```

It restores the dump into a throwaway `postgres:17` container, lists any of this code's
migrations that aren't in the backup yet (normal when the code is ahead of production), prints
row counts (users, trips, days, legs, confirmations, …) and removes the container. Neither the
dev database nor production is touched. It ends with `OK` or `RESTORE CHECK FAILED: …`.

**Restoring production for real** is James's call, after a `pg_dump` of whatever is there now.
Restore the dump with `pg_restore --clean --if-exists --no-owner -d travel_site`, copy the
day's `files/` back with `rsync`, then restart the app.

## Scheduled jobs and their emails

**Rule:** anything a script or scheduled job needs to tell James goes to the addresses in `DJANGO_ADMINS` (the same
`.env` value that receives web error emails) — never a crontab `MAILTO`, never another address setting
(script-emails plan M1).

- **Cron lines** go through `scripts/run_job.sh NAME [--report-on N] -- command …`: it keeps each run's output in
  `~/logs/sbl-jobs/NAME/` (60 days), stays quiet on exit 0 and emails DJANGO_ADMINS on any other exit ("NAME failed
  (exit N)" with the output's last 30 lines).
- **The shell scripts** (`backup_prod.sh`, `sync_dev_from_prod.sh`, `sync_staging_from_prod.sh`) email through
  `fail()` in `lib/sbl_common.sh` when they fail: the failure line and the log's last 30 lines. The systemd timers
  (`deploy/backup/`, `deploy/dev/`) need nothing else. `sbl_notify` sends through the clone's `manage.py
  notify_admins` when it has a `.venv`; otherwise (the backup machine) with `sendmail -t` and `DJANGO_ADMINS` /
  `SERVER_EMAIL` from that clone's `.env`. `bash scripts/backup_prod.sh --check` says which way it will mail.
- **Test the mail** from the app folder: `echo hello | .venv/bin/python manage.py notify_admins --subject test`
  (on production add `DJANGO_SETTINGS_MODULE=config.settings.prod`).

James's crontab on production (tazcomputer), replacing the old lines and any `MAILTO` (keep your own times if they
differ):

```
DJANGO_SETTINGS_MODULE=config.settings.prod
10 2 * * * bash /var/www/travel_site/scripts/run_job.sh recount_visitors -- .venv/bin/python manage.py recount_visitors
40 7 * * * bash /var/www/travel_site/scripts/run_job.sh send_trip_digests -- .venv/bin/python manage.py send_trip_digests
20 3 * * * bash /var/www/travel_site/scripts/run_job.sh purge_deleted_accounts -- .venv/bin/python manage.py purge_deleted_accounts
30 17 * * 1-5 bash /var/www/travel_site/scripts/run_job.sh fetch_rates -- .venv/bin/python manage.py fetch_rates
17 6 1 * * bash /var/www/travel_site/scripts/run_job.sh check_countries -- .venv/bin/python manage.py check_countries --email
15 5 * * * bash /var/www/travel_site/scripts/run_job.sh sync_staging -- bash /var/www/travel_site_staging/scripts/sync_staging_from_prod.sh
```

The first line gives every job — and the report `run_job.sh` sends when one fails — production's settings (the
staging sync sets staging's itself for its own steps).
`run_job.sh` runs the command from `/var/www/travel_site`, so `.venv/bin/python manage.py` is the app's.

## Monthly country check

`manage.py check_countries` compares our countries with REST Countries (name, ISO-3 code, currency code and name,
calling code, continent) and prints where they differ, then exits 1; nothing differing exits 0, and an API problem
(including a missing `RESTCOUNTRIES_API_KEY` in `.env`) exits 2. It stores nothing — their terms allow keeping their
data three days at most — so read the report and edit a country by hand (or by CSV import) if you agree. Three API
requests a run (the free plan allows 1,000 a month). With `--email` (the crontab line above) it emails the differences
to DJANGO_ADMINS itself and exits 0, so `run_job.sh` mails only an API failure. `--country ZW` checks one country
(one request).
