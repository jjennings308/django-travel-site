#!/usr/bin/bash
set -a; source .env; set +a
./reset_db.sh travel_site travelappuser postgres
python manage.py migrate
