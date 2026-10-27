# Shared helpers for the production scripts (sync_dev_from_prod.sh, backup_prod.sh, sync_staging_from_prod.sh,
# run_job.sh).
# Source it; it defines functions and the SSH command only, and runs nothing.
#
# The caller sets LOG (a file) before calling log/fail, and PROD_HOST before sbl_ssh.

# One timestamped line to stdout and $LOG.
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
# Log the failure, email it to DJANGO_ADMINS with the log's last 30 lines (sbl_notify), and exit 1.
fail() {
  log "FAILED: $*"
  { echo "FAILED: $*"; echo; echo "Host: $(hostname)  Log: $LOG"; echo "Last 30 lines:"; tail -n 30 "$LOG" 2>/dev/null; } \
    | sbl_notify "$(basename "$0") failed"
  exit 1
}

# Email stdin to DJANGO_ADMINS (script-emails plan M1). The rule: scripts and jobs tell James through DJANGO_ADMINS,
# never another address setting or a crontab MAILTO. Bodies hold counts, steps, paths and log tails: no secrets or
# personal data.
#   sbl_notify SUBJECT < body
# With the app on this machine ($SBL_NOTIFY_APP, else $APP: manage.py and .venv), through `manage.py notify_admins`,
# so its .env and mail settings are used (settings: $SBL_NOTIFY_SETTINGS, else $DJANGO_SETTINGS_MODULE, else
# manage.py's default). Without it (the backup machine), DJANGO_ADMINS and SERVER_EMAIL from that .env and
# `sendmail -t`. If neither works, one log line and carry on: a script never fails because of its own report.
sbl_notify_how() {  # prints "manage.py", "sendmail" or "none"
  local app="${SBL_NOTIFY_APP:-${APP:-}}"
  if [ -n "$app" ] && [ -f "$app/manage.py" ] && [ -x "$app/.venv/bin/python" ]; then echo manage.py; return; fi
  if [ -n "$app" ] && [ -r "$app/.env" ] && [ -n "$(envval DJANGO_ADMINS "$app/.env")" ] && command -v sendmail >/dev/null 2>&1; then
    echo sendmail; return
  fi
  echo none
}
sbl_notify() {
  local subject="$1" app="${SBL_NOTIFY_APP:-${APP:-}}" body how
  body="$(cat)"
  how="$(sbl_notify_how)"
  if [ "$how" = manage.py ]; then
    local settings="${SBL_NOTIFY_SETTINGS:-${DJANGO_SETTINGS_MODULE:-}}"
    printf '%s\n' "$body" | ( cd "$app" && env ${settings:+DJANGO_SETTINGS_MODULE="$settings"} \
      "$app/.venv/bin/python" manage.py notify_admins --subject "$subject" ) >/dev/null 2>&1 && return 0
  elif [ "$how" = sendmail ]; then
    local to from
    to="$(envval DJANGO_ADMINS "$app/.env")"
    from="$(envval SERVER_EMAIL "$app/.env")"
    printf 'To: %s\n%sSubject: [ShareBucketList job] %s\n\n%s\n' "$to" "${from:+From: $from
}" "$subject" "$body" | sendmail -t && return 0
  fi
  if [ -n "${LOG:-}" ]; then log "could not email DJANGO_ADMINS ($subject)"; else echo "could not email DJANGO_ADMINS ($subject)" >&2; fi
  return 0
}

# Read one value from an .env file without sourcing it (values contain spaces).
#   envval NAME [file]   (default: $APP/.env)
envval() { grep -m1 "^$1=" "${2:-$APP/.env}" | cut -d= -f2- | sed -E 's/^["'"'"'](.*)["'"'"']$/\1/'; }

# ssh to production, never prompting.
sbl_ssh() { ssh -o BatchMode=yes -o ConnectTimeout=20 "$PROD_HOST" "$@"; }

# Write a custom-format pg_dump of production to stdout. The remote commands go
# over stdin as a quoted heredoc, so nothing is expanded here; the password is
# read from the server's .env there and never printed or passed on a command line.
sbl_dump_prod() {
  sbl_ssh bash -s <<'REMOTE'
set -euo pipefail
cd /var/www/travel_site
envval() { grep -m1 "^$1=" .env | cut -d= -f2- | sed -E 's/^["'"'"'](.*)["'"'"']$/\1/'; }
PGPASSWORD="$(envval POSTGRES_PASSWORD)" pg_dump -h "$(envval POSTGRES_HOST)" -p "$(envval POSTGRES_PORT)" \
  -U "$(envval POSTGRES_USER)" -Fc "$(envval POSTGRES_DB)"
REMOTE
}

# How many tables have data in a dump (a real one has well over 50).
sbl_dump_tables() { pg_restore -l "$1" 2>/dev/null | grep -c "TABLE DATA"; }

# Retention: read dated names (YYYY-MM-DD, one per line, any order) on stdin and
# print the ones to keep: the newest $1 (daily), the newest in each of the $2 most
# recent ISO weeks (weekly) and the newest in each of the $3 most recent months
# (monthly). Pure: no files are touched, so it can be tested on its own.
sbl_keep() {
  local daily="$1" weekly="$2" monthly="$3"
  local -a dates
  mapfile -t dates < <(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' | sort -r -u)
  local -A keep=() seen_week=() seen_month=()
  local d week month weeks=0 months=0 i=0
  for d in "${dates[@]}"; do
    if (( i < daily )); then keep[$d]=1; fi
    i=$((i + 1))
    week=$(date -d "$d" +%G-%V)
    if [[ -z "${seen_week[$week]:-}" ]]; then
      seen_week[$week]=1
      if (( weeks < weekly )); then keep[$d]=1; fi
      weeks=$((weeks + 1))
    fi
    month=${d:0:7}
    if [[ -z "${seen_month[$month]:-}" ]]; then
      seen_month[$month]=1
      if (( months < monthly )); then keep[$d]=1; fi
      months=$((months + 1))
    fi
  done
  for d in "${dates[@]}"; do [[ -n "${keep[$d]:-}" ]] && echo "$d"; done
  return 0
}
