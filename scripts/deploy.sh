#!/usr/bin/env bash
# Deploy the latest `main` to production. Run ON the server:
#     bash /var/www/travel_site/scripts/deploy.sh
# Steps: pull -> install requirements -> check --deploy -> (backup +) migrate ->
# collectstatic --clear -> restart (sudo) -> live check. Stops at the first failure;
# the running site keeps serving until the restart.
set -euo pipefail
APP=/var/www/travel_site
SITE=https://sharebucketlist.com
cd "$APP"
umask 002                                   # files stay group-writable for www-data
export DJANGO_SETTINGS_MODULE=config.settings.prod
PY="$APP/.venv/bin/python"

echo "== code (was $(git log --oneline -1))"
# staticfiles/ is build output and no longer tracked. On a checkout from before that
# change, discard the re-collected copies so the pull can remove them (collectstatic
# below recreates everything).
if git ls-files --error-unmatch staticfiles >/dev/null 2>&1; then
  git checkout -- staticfiles
fi
git pull --ff-only
echo "   now $(git log --oneline -1)"

echo "== requirements"
"$APP/.venv/bin/pip" install -q -r requirements.txt

echo "== checks"
"$PY" manage.py check --deploy

echo "== migrations"
if ! "$PY" manage.py migrate --check >/dev/null 2>&1; then
  mkdir -p ~/backups && chmod 700 ~/backups
  BACKUP=~/backups/travel_site_$(date +%Y%m%d-%H%M%S).dump
  # Read only the DB keys (sourcing .env would break on unquoted values with spaces).
  envval() { grep -m1 "^$1=" "$APP/.env" | cut -d= -f2- | sed -E 's/^["'"'"'](.*)["'"'"']$/\1/'; }
  PGPASSWORD="$(envval POSTGRES_PASSWORD)" pg_dump -h "$(envval POSTGRES_HOST)" \
      -U "$(envval POSTGRES_USER)" -d "$(envval POSTGRES_DB)" -Fc -f "$BACKUP"
  chmod 600 "$BACKUP"
  echo "   backup before migrating: $BACKUP"
  "$PY" manage.py migrate --noinput
else
  echo "   none pending"
fi

echo "== static files"
"$PY" manage.py collectstatic --noinput --clear | tail -1

echo "== restart (sudo)"
sudo systemctl restart travel_site
sleep 3
systemctl is-active travel_site

echo "== live check"
printf '   %-8s %s\n' "/" "$(curl -s -o /dev/null -w '%{http_code}' "$SITE/")"
CSS=$(curl -s "$SITE/accounts/login/" | grep -oE '/static/css/dist/styles[^"]*\.css' | head -1)
printf '   %-8s %s -> %s\n' "css" "${CSS:-not found}" "$(curl -s -o /dev/null -w '%{http_code}' "$SITE$CSS")"
