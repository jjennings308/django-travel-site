#!/usr/bin/env bash
# Run a scheduled job, keep its output, and email DJANGO_ADMINS when it fails (script-emails plan M1).
#
#   bash scripts/run_job.sh NAME [--report-on N] -- command [args…]
#
# The command's output (stdout and stderr) goes to ~/logs/sbl-jobs/NAME/<date>T<time>.log ($SBL_JOB_LOGS to change
# the folder); logs older than 60 days are deleted. Exit 0 is quiet. Any other exit sends one email to DJANGO_ADMINS
# ("NAME failed (exit N)" with the output's last 30 lines) through sbl_notify, and run_job.sh exits with the
# command's code. --report-on N treats exit N as "something to look at" instead: the whole output is mailed as
# "NAME: something to look at (exit N)". The rule: jobs report through DJANGO_ADMINS, never a crontab MAILTO.
#
# The app is the clone this script is in (its manage.py and .venv send the mail); cron sets DJANGO_SETTINGS_MODULE
# for production (scripts/README.md lists the crontab lines).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="${SBL_APP:-$(cd "$HERE/.." && pwd)}"
KEEP_DAYS=60

usage() { echo "usage: run_job.sh NAME [--report-on N] -- command [args…]" >&2; exit 64; }
[ $# -ge 3 ] || usage
NAME="$1"; shift
case "$NAME" in ""|*/*|.*) usage ;; esac
REPORT_ON=""
if [ "${1:-}" = "--report-on" ]; then REPORT_ON="${2:-}"; shift 2 || usage; fi
[ "${1:-}" = "--" ] || usage
shift
[ $# -ge 1 ] || usage

DIR="${SBL_JOB_LOGS:-$HOME/logs/sbl-jobs}/$NAME"
mkdir -p "$DIR"
LOG="$DIR/$(date '+%Y-%m-%dT%H%M%S').log"
# log, envval, sbl_notify
. "$HERE/lib/sbl_common.sh"

{ echo "$(date '+%Y-%m-%d %H:%M:%S') $NAME: $*"; } >> "$LOG"
( cd "$APP" && "$@" ) >> "$LOG" 2>&1
rc=$?
echo "$(date '+%Y-%m-%d %H:%M:%S') $NAME: exit $rc" >> "$LOG"

if [ "$rc" -ne 0 ]; then
  if [ -n "$REPORT_ON" ] && [ "$rc" = "$REPORT_ON" ]; then
    { echo "$NAME on $(hostname): something to look at."; echo; sed '1d;$d' "$LOG"; } \
      | sbl_notify "$NAME: something to look at (exit $rc)"
  else
    { echo "$NAME on $(hostname) failed (exit $rc). Log: $LOG"; echo; echo "Last 30 lines:"; tail -n 30 "$LOG"; } \
      | sbl_notify "$NAME failed (exit $rc)"
  fi
fi

find "$DIR" -maxdepth 1 -name '*.log' -type f -mtime +"$KEEP_DAYS" -delete 2>/dev/null
exit "$rc"
