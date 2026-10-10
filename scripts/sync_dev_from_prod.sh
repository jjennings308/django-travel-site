#!/usr/bin/env bash
# Make the dev database a copy of production (production is only read).
#
#   bash scripts/sync_dev_from_prod.sh          # run now
#   systemctl --user start sbl-dev-sync         # same, via the nightly timer's service
#
# Steps: lock -> dump production over SSH (checked before anything changes) ->
# back up dev -> restore into dev -> migrate dev -> copy new uploads (add-only)
# -> compare row counts -> prune old sync dumps -> one line in sync.log.
# Anything done only in the dev database is replaced. This is a dev convenience,
# not a production backup.
#
# Overridable for testing: SBL_PROD_HOST, SBL_BACKUP_DIR, SBL_KEEP_DAYS.
set -uo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
PROD_HOST="${SBL_PROD_HOST:-james@tazcomputer.com}"
PROD_APP=/var/www/travel_site
BACKUPS="${SBL_BACKUP_DIR:-$HOME/db_backups}"
KEEP_DAYS="${SBL_KEEP_DAYS:-14}"
PY="$APP/.venv/bin/python"
LOG="$BACKUPS/sync.log"
TS="$(date +%Y%m%d-%H%M%S)"
PROD_DUMP="$BACKUPS/travel_site_prod_$TS.dump"
DEV_DUMP="$BACKUPS/travel_site_dev_pre_sync_$TS.dump"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=20 "$PROD_HOST")

mkdir -p "$BACKUPS"
cd "$APP" || exit 1

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
fail() { log "FAILED: $*"; exit 1; }
# Read one value from dev's .env without sourcing it (values contain spaces).
envval() { grep -m1 "^$1=" "$APP/.env" | cut -d= -f2- | sed -E 's/^["'"'"'](.*)["'"'"']$/\1/'; }

exec 9>"$BACKUPS/.sync.lock"
flock -n 9 || { log "skipped: another sync is running"; exit 0; }
if pgrep -f "manage.py test" >/dev/null; then
  log "skipped: a test run is in progress"; exit 0
fi

# 1. Dump production. Nothing in dev changes until this dump is known good.
# The remote commands go over stdin as a quoted heredoc, so nothing is expanded
# here; the password is read from the server's .env there and never printed.
"${SSH[@]}" bash -s > "$PROD_DUMP" 2>>"$LOG" <<'REMOTE' || { rm -f "$PROD_DUMP"; fail "could not dump production (SSH to $PROD_HOST or pg_dump)"; }
set -euo pipefail
cd /var/www/travel_site
envval() { grep -m1 "^$1=" .env | cut -d= -f2- | sed -E 's/^["'"'"'](.*)["'"'"']$/\1/'; }
PGPASSWORD="$(envval POSTGRES_PASSWORD)" pg_dump -h "$(envval POSTGRES_HOST)" -p "$(envval POSTGRES_PORT)" \
  -U "$(envval POSTGRES_USER)" -Fc "$(envval POSTGRES_DB)"
REMOTE
chmod 600 "$PROD_DUMP"
TABLES=$(pg_restore -l "$PROD_DUMP" 2>/dev/null | grep -c "TABLE DATA")
[ "${TABLES:-0}" -gt 50 ] || { rm -f "$PROD_DUMP"; fail "production dump looks wrong ($TABLES tables); dev left unchanged"; }

# 2. Back up dev.
DEV_USER="$(envval POSTGRES_USER)"; DEV_DB="$(envval POSTGRES_DB)"
docker exec postgres pg_dump -U "$DEV_USER" -Fc "$DEV_DB" > "$DEV_DUMP" 2>>"$LOG" \
  || { rm -f "$DEV_DUMP"; fail "could not back up dev (is the postgres container running?); dev left unchanged"; }
chmod 600 "$DEV_DUMP"

# 3. Restore production into dev. The only expected message is Postgres 17's
#    transaction_timeout setting, unknown to dev's Postgres 16.
ERRORS=$(PGPASSWORD="$(envval POSTGRES_PASSWORD)" pg_restore -h "$(envval POSTGRES_HOST)" -p "$(envval POSTGRES_PORT)" \
  -U "$DEV_USER" -d "$DEV_DB" --clean --if-exists --no-owner --no-privileges "$PROD_DUMP" 2>&1 \
  | grep -v -e 'transaction_timeout' -e '^$' -e 'errors ignored on restore: 1$')
[ -z "$ERRORS" ] || { printf '%s\n' "$ERRORS" >> "$LOG"; fail "restore reported errors (dev backup: $DEV_DUMP)"; }

# 4. Re-apply any migrations that exist in dev's code but not yet on production.
"$PY" manage.py migrate --noinput >>"$LOG" 2>&1 || fail "migrate failed after restore (dev backup: $DEV_DUMP)"

# 5. Uploads: copy new production files; never delete or overwrite dev's.
rsync -a --ignore-existing "$PROD_HOST:$PROD_APP/uploads/" "$APP/uploads/" 2>>"$LOG" || log "warning: uploads copy failed"

# 6. Compare row counts.
COUNTS='
from django.contrib.auth import get_user_model
from apps.trips.models import Trip
from apps.events.models import Event
from apps.activities.models import Activity
from apps.locations.models import City
from apps.bucketlists.models import BucketListItem
print("users", get_user_model().objects.count(), "trips", Trip.objects.count(), "events", Event.objects.count(),
      "activities", Activity.objects.count(), "cities", City.objects.count(), "bucket", BucketListItem.objects.count())'
DEV_COUNTS=$("$PY" manage.py shell -c "$COUNTS" 2>/dev/null | grep '^users')
PROD_COUNTS=$("${SSH[@]}" "cd $PROD_APP && DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py shell -c '$COUNTS'" 2>/dev/null | grep '^users')
[ -n "$DEV_COUNTS" ] && [ "$DEV_COUNTS" = "$PROD_COUNTS" ] \
  || fail "counts differ after restore: dev [$DEV_COUNTS] prod [$PROD_COUNTS]"

# 7. Prune this script's own dumps (hand-made phase backups are left alone).
find "$BACKUPS" -maxdepth 1 -type f \( -name 'travel_site_prod_*.dump' -o -name 'travel_site_dev_pre_sync_*.dump' \) \
  -mtime +"$KEEP_DAYS" -delete

log "ok: dev = production ($DEV_COUNTS); backups $(basename "$PROD_DUMP"), $(basename "$DEV_DUMP")"
