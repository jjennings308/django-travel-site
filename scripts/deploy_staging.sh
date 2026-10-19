#!/usr/bin/env bash
# Put a branch on staging.sharebucketlist.com (site roadmap R16). Run ON the server:
#     bash /var/www/travel_site_staging/scripts/deploy_staging.sh [branch]    # default: main
# Checks out the branch in the staging clone, then runs the same scripts/deploy.sh as production with
# staging's folder, settings, service and site. SBL_CURL_AUTH ("user:password" for the basic auth)
# is read from staging's .env (STAGING_BASIC_AUTH) so the live check can get past it.
set -euo pipefail
APP=/var/www/travel_site_staging
BRANCH="${1:-main}"
cd "$APP"
git fetch --quiet origin
git checkout --quiet "$BRANCH"
git reset --quiet --hard "origin/$BRANCH"     # staging follows the remote branch exactly
AUTH="$(grep -m1 '^STAGING_BASIC_AUTH=' .env | cut -d= -f2- || true)"
SBL_APP="$APP" SBL_SITE=https://staging.sharebucketlist.com SBL_SETTINGS=config.settings.staging \
  SBL_SERVICE=travel_site_staging SBL_CURL_AUTH="$AUTH" bash "$APP/scripts/deploy.sh"
