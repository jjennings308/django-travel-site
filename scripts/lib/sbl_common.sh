# Shared helpers for the production scripts (sync_dev_from_prod.sh, backup_prod.sh).
# Source it; it defines functions and the SSH command only, and runs nothing.
#
# The caller sets LOG (a file) before calling log/fail, and PROD_HOST before sbl_ssh.

# One timestamped line to stdout and $LOG.
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
fail() { log "FAILED: $*"; exit 1; }

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
