#!/usr/bin/env bash

set -euo pipefail

ENV_FILE=".env"

envval() {
    grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- | sed -E "s/^[\"'](.*)[\"']$/\1/"
}

BACKUP="$HOME/backups/travel_site_pre_s1_$(date +%Y%m%d-%H%M%S).dump"

mkdir -p "$(dirname "$BACKUP")"

export PGPASSWORD="$(envval POSTGRES_PASSWORD)"

pg_dump \
    -h "$(envval POSTGRES_HOST)" \
    -U "$(envval POSTGRES_USER)" \
    -d "$(envval POSTGRES_DB)" \
    -Fc \
    -f "$BACKUP"

chmod 600 "$BACKUP"

echo "Backup created:"
ls -l "$BACKUP"