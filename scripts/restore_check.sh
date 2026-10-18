#!/usr/bin/env bash
# Restore drill: prove a backup dump restores and is usable. Run it monthly.
#
#   bash scripts/restore_check.sh ~/backups/sharebucketlist/db/2026-10-18.dump
#
# Needs Docker and this repo with its .venv (so: the dev machine; copy a dump over from
# the backup machine with scp first, see scripts/README.md). It starts a throwaway
# postgres:17 container on a random local port, restores the dump into it, checks the
# migrations against this code and prints row counts of the main tables, then removes
# the container. The dev database and production are never touched: Django is pointed
# at the container through POSTGRES_* in the environment, which win over .env.
set -uo pipefail

DUMP="${1:-}"
[ -n "$DUMP" ] && [ -r "$DUMP" ] || { echo "usage: $0 <dump file>" >&2; exit 2; }
APP="$(cd "$(dirname "$0")/.." && pwd)"
PY="$APP/.venv/bin/python"
NAME="sbl-restore-check-$$"
PASS="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1; }
trap cleanup EXIT
step() { printf '\n== %s\n' "$*"; }
die() { echo "RESTORE CHECK FAILED: $*" >&2; exit 1; }

step "Dump: $DUMP ($(du -h "$DUMP" | cut -f1), $(pg_restore -l "$DUMP" 2>/dev/null | grep -c 'TABLE DATA') tables with data)"
pg_restore -l "$DUMP" >/dev/null 2>&1 || die "pg_restore cannot read it"

step "Starting a throwaway postgres:17"
docker run -d --rm --name "$NAME" -e POSTGRES_USER=check -e POSTGRES_PASSWORD="$PASS" -e POSTGRES_DB=check \
  -p 127.0.0.1::5432 postgres:17 >/dev/null || die "could not start the container"
for _ in $(seq 60); do docker exec "$NAME" pg_isready -U check -d check -q 2>/dev/null && break; sleep 1; done
docker exec "$NAME" pg_isready -U check -d check -q || die "Postgres did not start"
PORT="$(docker port "$NAME" 5432/tcp | head -1 | sed 's/.*://')"
export POSTGRES_HOST=127.0.0.1 POSTGRES_PORT="$PORT" POSTGRES_DB=check POSTGRES_USER=check POSTGRES_PASSWORD="$PASS"

step "Restoring"
ERRORS=$(PGPASSWORD="$PASS" pg_restore -h 127.0.0.1 -p "$PORT" -U check -d check --no-owner --no-privileges "$DUMP" 2>&1)
[ -z "$ERRORS" ] || { printf '%s\n' "$ERRORS" | tail -20; die "pg_restore reported errors"; }
echo "restored"

cd "$APP" || exit 1
step "Migrations (this code vs the backup)"
if "$PY" manage.py migrate --check >/dev/null 2>&1; then
  echo "all of this code's migrations are in the backup"
else
  echo "not yet in the backup (normal when this code is ahead of production):"
  "$PY" manage.py showmigrations --plan 2>/dev/null | grep '^\[ \]' || die "could not read migrations"
fi

step "Row counts"
"$PY" manage.py shell -c '
from django.contrib.auth import get_user_model
from apps.trips.models import Trip, Day, TransportLeg, Confirmation, TripGrant
from apps.events.models import Event
from apps.activities.models import Activity
from apps.locations.models import City
from apps.bucketlists.models import BucketListItem
from apps.media_app.models import Media
for name, model in [("users", get_user_model()), ("trips", Trip), ("days", Day), ("legs", TransportLeg),
                    ("confirmations", Confirmation), ("trip grants", TripGrant), ("events", Event),
                    ("activities", Activity), ("cities", City), ("bucket items", BucketListItem), ("media", Media)]:
    print(f"{name:>14} {model._base_manager.count()}")
' || die "Django could not read the restored database"

USERS=$(PGPASSWORD="$PASS" psql -h 127.0.0.1 -p "$PORT" -U check -d check -Atc 'select count(*) from users' 2>/dev/null \
  || docker exec "$NAME" psql -U check -d check -Atc 'select count(*) from users')
[ "${USERS:-0}" -gt 0 ] || die "no users in the restored database"
step "OK: the backup restores and Django can read it"
