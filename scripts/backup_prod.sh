#!/usr/bin/env bash
# Back up ShareBucketList production onto this machine (production is only read).
#
#   bash scripts/backup_prod.sh            # run now
#   bash scripts/backup_prod.sh --check    # check the prerequisites; changes nothing
#   systemctl --user start sbl-backup      # same as a run, via the daily timer's service
#
# Runs on the backup machine (popsicletoes.us), not on production and not in the repo's
# virtualenv: it needs ssh (a key for $PROD_HOST), rsync, flock and pg_restore 17+.
# It needs this file and lib/sbl_common.sh beside it — a clone of the repo, or the two copied.
#
# Layout under $SBL_BACKUP_ROOT (default ~/backups/sharebucketlist):
#   db/YYYY-MM-DD.dump          pg_dump -Fc, checked with pg_restore --list
#   files/YYYY-MM-DD/uploads/   rsync snapshots; unchanged files are hard links to the
#   files/YYYY-MM-DD/private_uploads/   previous day's (--link-dest), so each day is complete
#   backup.log                  one line per run
# Retention: 14 daily, 8 weekly, 12 monthly (sbl_keep), for dumps and snapshots alike.
# A failed run exits 1 (the unit shows failed in the journal) and prunes nothing.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROD_HOST="${SBL_PROD_HOST:-james@tazcomputer.com}"
PROD_APP="${SBL_PROD_APP:-/var/www/travel_site}"
ROOT="${SBL_BACKUP_ROOT:-$HOME/backups/sharebucketlist}"
KEEP_DAILY=14 KEEP_WEEKLY=8 KEEP_MONTHLY=12
LOG="$ROOT/backup.log"
DAY="$(date +%F)"
# log, fail, sbl_ssh, sbl_dump_prod, sbl_dump_tables, sbl_keep
. "$HERE/lib/sbl_common.sh"

if [ "${1:-}" = "--check" ]; then
  ok=1
  say() { printf '%-28s %s\n' "$1" "$2"; }
  for tool in ssh rsync flock pg_restore; do
    if command -v "$tool" >/dev/null; then say "$tool" "found"; else say "$tool" "MISSING"; ok=0; fi
  done
  if command -v pg_restore >/dev/null; then
    major=$(pg_restore --version | grep -oE '[0-9]+' | head -1)
    if [ "${major:-0}" -ge 17 ]; then say "pg_restore version" "$major (ok)"
    else say "pg_restore version" "$major — need 17+ (apt install postgresql-client-17)"; ok=0; fi
  fi
  if sbl_ssh true 2>/dev/null; then say "ssh $PROD_HOST" "ok"
  else say "ssh $PROD_HOST" "FAILED — add this machine's key to production's ~/.ssh/authorized_keys"; ok=0; fi
  if [ "$ok" = 1 ] && sbl_ssh "test -r $PROD_APP/.env && test -r $PROD_APP/uploads && test -r $PROD_APP/private_uploads" 2>/dev/null; then
    say "production files readable" "ok"
  elif [ "$ok" = 1 ]; then say "production files readable" "FAILED (.env, uploads/ or private_uploads/)"; ok=0; fi
  say "backups go to" "$ROOT ($(df -h "$(dirname "$ROOT")" 2>/dev/null | awk 'NR==2 {print $4 " free"}'))"
  [ "$ok" = 1 ] && { echo "Ready."; exit 0; } || { echo "Not ready; fix the lines above."; exit 1; }
fi

mkdir -p "$ROOT/db" "$ROOT/files"
chmod 700 "$ROOT"
exec 9>"$ROOT/.backup.lock"
flock -n 9 || { log "skipped: another backup is running"; exit 0; }

# 1. Database: dump to a partial file, check it, then put it in place.
PART="$ROOT/db/.$DAY.dump.partial"
( umask 077; sbl_dump_prod > "$PART" 2>>"$LOG" ) || { rm -f "$PART"; fail "could not dump production (SSH to $PROD_HOST or pg_dump)"; }
TABLES=$(sbl_dump_tables "$PART")
[ "${TABLES:-0}" -gt 50 ] || { rm -f "$PART"; fail "production dump looks wrong ($TABLES tables with data); kept the earlier backups"; }
mv -f "$PART" "$ROOT/db/$DAY.dump"

# 2. Files: a new dated snapshot, hard-linking what the latest earlier one already has.
PREV=$(find "$ROOT/files" -mindepth 1 -maxdepth 1 -type d -name '????-??-??' \
  ! -name "$DAY" -printf '%f\n' 2>/dev/null | sort | tail -1)
SNAP="$ROOT/files/.$DAY.partial"
rm -rf "$SNAP"
for dir in uploads private_uploads; do
  mkdir -p "$SNAP/$dir"
  link=()
  [ -n "$PREV" ] && link=(--link-dest="$ROOT/files/$PREV/$dir")
  rsync -a --delete "${link[@]}" -e "ssh -o BatchMode=yes -o ConnectTimeout=20" \
    "$PROD_HOST:$PROD_APP/$dir/" "$SNAP/$dir/" 2>>"$LOG" \
    || { rm -rf "$SNAP"; fail "could not copy $dir (database backup $DAY.dump is kept)"; }
done
chmod 700 "$SNAP/private_uploads"
rm -rf "$ROOT/files/$DAY"
mv "$SNAP" "$ROOT/files/$DAY"

# 3. Retention — only after a good run, so the newest backups are never the ones pruned.
prune() {  # prune <dir> <suffix>: delete dated entries sbl_keep doesn't keep
  local dir="$1" suffix="$2" name
  local -A keep=()
  while read -r name; do keep[$name]=1; done < <(
    find "$dir" -mindepth 1 -maxdepth 1 -name "????-??-??$suffix" -printf '%f\n' | sed "s/$suffix\$//" \
      | sbl_keep "$KEEP_DAILY" "$KEEP_WEEKLY" "$KEEP_MONTHLY")
  find "$dir" -mindepth 1 -maxdepth 1 -name "????-??-??$suffix" -printf '%f\n' | while read -r name; do
    [ -n "${keep[${name%"$suffix"}]:-}" ] || rm -rf "${dir:?}/$name"
  done
}
prune "$ROOT/db" ".dump"
prune "$ROOT/files" ""

SIZE=$(du -sh "$ROOT/db/$DAY.dump" | cut -f1)
COUNT=$(find "$ROOT/db" -name '????-??-??.dump' | wc -l)
FILES=$(find "$ROOT/files/$DAY" -type f | wc -l)
log "ok: $DAY.dump ($SIZE, $TABLES tables), files/$DAY ($FILES files); $COUNT dumps kept"
