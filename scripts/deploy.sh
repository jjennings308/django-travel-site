#!/usr/bin/env bash
# Deploy the latest `main` to production. Run ON the server:
#     bash /var/www/travel_site/scripts/deploy.sh
# Steps: sudo up front -> pull -> install requirements -> check --deploy -> (backup +)
# migrate -> collectstatic (keeping the old hashed files) -> restart (sudo) -> live check (home, stylesheet, /healthz/)
# -> prune stale static files. Stops at the first failure; the running site keeps serving
# (with its own static files still on disk) until the restart.
#
# Why the old files are kept: production uses ManifestStaticFilesStorage, so the running
# gunicorn links pages to the hashed names it loaded at start-up (styles.<hash>.css). A
# `collectstatic --clear` before a restart that then didn't happen (sudo prompt cancelled)
# deleted those files and left the site unstyled. Now the old names stay until a restart
# has succeeded, and stale ones are pruned only once they're a week old.
set -euo pipefail
APP=/var/www/travel_site
SITE=https://sharebucketlist.com
cd "$APP"
umask 002                                   # files stay group-writable for www-data
export DJANGO_SETTINGS_MODULE=config.settings.prod
PY="$APP/.venv/bin/python"

echo "== sudo (asked now so the restart at the end can't fail half-way)"
sudo -v

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

echo "== private uploads"
# Role-request documents etc.: outside MEDIA_ROOT so nginx never serves them. Group
# www-data (the repo directory is setgid), writable by the app, nothing for others.
mkdir -p "$APP/private_uploads" && chmod 2770 "$APP/private_uploads"

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
# No --clear: the running app still links to the previous hashed files until it restarts.
"$PY" manage.py collectstatic --noinput | tail -1

echo "== restart (sudo)"
sudo systemctl restart travel_site
sleep 3
systemctl is-active travel_site

echo "== live check"
HOME_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$SITE/")
printf '   %-8s %s\n' "/" "$HOME_STATUS"
CSS=$(curl -s "$SITE/accounts/login/" | grep -oE '/static/css/dist/styles[^"]*\.css' | head -1)
CSS_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$SITE$CSS")
printf '   %-8s %s -> %s\n' "css" "${CSS:-not found}" "$CSS_STATUS"
HEALTH_STATUS=$(curl -s -o /dev/null -w '%{http_code}' "$SITE/healthz/")
printf '   %-8s %s\n' "/healthz" "$HEALTH_STATUS"
if [ "$HOME_STATUS" != "200" ] || [ -z "$CSS" ] || [ "$CSS_STATUS" != "200" ] || [ "$HEALTH_STATUS" != "200" ]; then
  echo "!! The live site isn't right (home $HOME_STATUS, stylesheet ${CSS_STATUS:-none}, health $HEALTH_STATUS)."
  echo "!! Try: sudo systemctl restart travel_site   then run this script again."
  exit 1
fi

echo "== prune stale static files"
# Hashed copies (name.<12 hex>.ext) the current manifest no longer uses, once a week old.
"$PY" - <<'PRUNE'
import json, os, re, time
root = "staticfiles"
with open(os.path.join(root, "staticfiles.json")) as f:
    keep = set(json.load(f)["paths"].values())
hashed = re.compile(r"\.[0-9a-f]{12}\.[^./]+$")
cutoff, removed = time.time() - 7 * 86400, 0
for folder, _dirs, files in os.walk(root):
    for name in files:
        path = os.path.join(folder, name)
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if hashed.search(name) and rel not in keep and os.path.getmtime(path) < cutoff:
            os.remove(path)
            removed += 1
print(f"   removed {removed} stale file(s)")
PRUNE
