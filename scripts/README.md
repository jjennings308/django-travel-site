# Project Scripts

## reset_db.sh
Safely drops and recreates the local Docker Postgres database.

Usage:

set -a; source .env; set +a
./scripts/reset_db.sh
python manage.py migrate


**WARNING:** This deletes all data in the configured database.
