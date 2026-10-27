#!/usr/bin/env bash
# Copy production into staging, disguised (site roadmap R16). Runs ON the server, as james, nightly
# from cron (deploy/staging/README.md); production is only read.
#
#   bash /var/www/travel_site_staging/scripts/sync_staging_from_prod.sh
#
# Steps: lock -> dump production (checked) -> restore into the staging database -> disguise
# (scripts/staging_disguise.sql: emails, phones, travel documents) -> migrate (staging's code may
# be ahead) -> copy new public uploads (add-only; never private_uploads) -> one log line.
# Overridable for testing: SBL_PROD_APP, SBL_STAGING_APP, SBL_STAGING_LOG.
set -uo pipefail

PROD_APP="${SBL_PROD_APP:-/var/www/travel_site}"
STAGING_APP="${SBL_STAGING_APP:-/var/www/travel_site_staging}"
LOG="${SBL_STAGING_LOG:-$HOME/backups/staging_sync.log}"
DUMP="$(mktemp --suffix=.dump)"
trap 'rm -f "$DUMP"' EXIT
# log, fail, envval
APP="$STAGING_APP"
# A failure is emailed to DJANGO_ADMINS through production's manage.py and settings: staging's mail only goes to the
# console (script-emails plan M1).
SBL_NOTIFY_APP="$PROD_APP" SBL_NOTIFY_SETTINGS=config.settings.prod
. "$STAGING_APP/scripts/lib/sbl_common.sh"
mkdir -p "$(dirname "$LOG")"

exec 9>"$HOME/.staging_sync.lock"
flock -n 9 || { log "skipped: another staging sync is running"; exit 0; }

pg() {  # pg <app dir> <command> [args…]: run a Postgres client with that app's database settings
  local app="$1"; shift
  PGPASSWORD="$(envval POSTGRES_PASSWORD "$app/.env")" "$@" -h "$(envval POSTGRES_HOST "$app/.env")" \
    -p "$(envval POSTGRES_PORT "$app/.env")" -U "$(envval POSTGRES_USER "$app/.env")"
}

# 1. Dump production (read only).
pg "$PROD_APP" pg_dump -Fc -d "$(envval POSTGRES_DB "$PROD_APP/.env")" > "$DUMP" 2>>"$LOG" \
  || fail "could not dump production"
TABLES=$(pg_restore -l "$DUMP" 2>/dev/null | grep -c "TABLE DATA")
[ "${TABLES:-0}" -gt 50 ] || fail "production dump looks wrong ($TABLES tables); staging left unchanged"

# 2. Restore into staging (its own database and role).
STAGING_DB="$(envval POSTGRES_DB "$STAGING_APP/.env")"
[ "$STAGING_DB" != "$(envval POSTGRES_DB "$PROD_APP/.env")" ] || fail "staging and production name the same database"
ERRORS=$(pg "$STAGING_APP" pg_restore -d "$STAGING_DB" --clean --if-exists --no-owner --no-privileges "$DUMP" 2>&1 \
  | grep -v -e '^$' -e 'errors ignored on restore')
[ -z "$ERRORS" ] || { printf '%s\n' "$ERRORS" >> "$LOG"; fail "restore reported errors"; }

# 3. Disguise.
pg "$STAGING_APP" psql -d "$STAGING_DB" -v ON_ERROR_STOP=1 -q -f "$STAGING_APP/scripts/staging_disguise.sql" >>"$LOG" 2>&1 \
  || fail "disguise failed — staging holds an undisguised copy; stop it: sudo systemctl stop travel_site_staging"

# 4. Migrate (staging may run a branch ahead of production).
( cd "$STAGING_APP" && DJANGO_SETTINGS_MODULE=config.settings.staging .venv/bin/python manage.py migrate --noinput ) \
  >>"$LOG" 2>&1 || fail "migrate failed"

# 5. Public uploads only (photos, pictures); tickets and role documents stay on production.
rsync -a --ignore-existing "$PROD_APP/uploads/" "$STAGING_APP/uploads/" 2>>"$LOG" || log "warning: uploads copy failed"

USERS=$(pg "$STAGING_APP" psql -d "$STAGING_DB" -Atc "select count(*) from users")
REAL=$(pg "$STAGING_APP" psql -d "$STAGING_DB" -Atc "select count(*) from users where email not like '%@staging.invalid'")
[ "$REAL" = "0" ] || fail "$REAL account(s) still have a real email after disguising"
log "ok: staging = production ($TABLES tables, $USERS accounts, all disguised)"
