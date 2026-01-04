#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./scripts/reset_db.sh [db_name] [db_user] [pg_container]
DB_NAME="${1:-travel_site}"
DB_USER="${2:-travelappuser}"
PG_CONTAINER="${3:-postgres}"

# Requires POSTGRES_PASSWORD to be set in environment
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is not set. Try: set -a; source .env; set +a}"

echo "Backing up ${DB_NAME}..."
mkdir -p "$HOME/db_backups"
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -t "$PG_CONTAINER" \
  pg_dump -U "$DB_USER" -d "$DB_NAME" > "$HOME/db_backups/${DB_NAME}_$(date +%F_%H%M).sql"

echo "Terminating connections to ${DB_NAME}..."
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -it "$PG_CONTAINER" \
  psql -U "$DB_USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();"

echo "Dropping and recreating ${DB_NAME}..."
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -it "$PG_CONTAINER" \
  psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS ${DB_NAME};"

docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -it "$PG_CONTAINER" \
  psql -U "$DB_USER" -d postgres -c "CREATE DATABASE ${DB_NAME};"

docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" -it "$PG_CONTAINER" \
  psql -U "$DB_USER" -d postgres -c "ALTER DATABASE ${DB_NAME} OWNER TO ${DB_USER};"

echo "Done. Now run:"
echo "  python manage.py migrate"
