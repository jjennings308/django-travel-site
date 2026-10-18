# Project Scripts

## reset_db.sh
Safely drops and recreates the local Docker Postgres database.

Usage:

set -a; source .env; set +a
./scripts/reset_db.sh
python manage.py migrate


**WARNING:** This deletes all data in the configured database.

## Production backups (backup_prod.sh, on popsicletoes.us)

`backup_prod.sh` copies production onto the backup machine every night, and only ever reads
production. It writes:

- `~/backups/sharebucketlist/db/YYYY-MM-DD.dump`: the database (`pg_dump -Fc`), checked
  before it is kept;
- `~/backups/sharebucketlist/files/YYYY-MM-DD/`: `uploads/` and `private_uploads/`. Files that
  didn't change share disk space with the day before (hard links), so every day is a full copy.

It keeps 14 daily, 8 weekly and 12 monthly backups, and writes one line per run to
`~/backups/sharebucketlist/backup.log`. A failed run exits 1, deletes nothing, and shows as
failed in `systemctl --user status sbl-backup`.

**Set up once on popsicletoes.us:**

```bash
sudo apt install rsync postgresql-client-17           # pg_restore must be 17 or newer
ssh-keygen -t ed25519                                  # if ~/.ssh has no key yet
ssh-copy-id james@tazcomputer.com                      # lets the backup log in to production
git clone git@github.com:jjennings308/django-travel-site.git ~/projects/travel_site
bash ~/projects/travel_site/scripts/backup_prod.sh --check     # every line should say ok; changes nothing
bash ~/projects/travel_site/scripts/backup_prod.sh             # the first backup, now
cp ~/projects/travel_site/deploy/backup/sbl-backup.* ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now sbl-backup.timer
loginctl enable-linger $USER                           # so it runs while logged out
```

The clone only provides the scripts; it needs no virtualenv or `.env`. Run `git pull` there
when the scripts change.

**Checking on it:** `tail ~/backups/sharebucketlist/backup.log`,
`systemctl --user list-timers sbl-backup.timer`, `journalctl --user -u sbl-backup`.

## Restore drill (restore_check.sh, monthly, on the dev machine)

It proves a backup can be restored. It needs Docker and the repo's `.venv`, so run it on the dev
machine (use whatever name reaches the backup machine from there):

```bash
scp popsicletoes.us:backups/sharebucketlist/db/$(date +%F).dump ~/db_backups/drill.dump
bash scripts/restore_check.sh ~/db_backups/drill.dump && rm ~/db_backups/drill.dump
```

It restores the dump into a throwaway `postgres:17` container, lists any of this code's
migrations that aren't in the backup yet (normal when the code is ahead of production), prints
row counts (users, trips, days, legs, confirmations, …) and removes the container. Neither the
dev database nor production is touched. It ends with `OK` or `RESTORE CHECK FAILED: …`.

**Restoring production for real** is James's call, after a `pg_dump` of whatever is there now.
Restore the dump with `pg_restore --clean --if-exists --no-owner -d travel_site`, copy the
day's `files/` back with `rsync`, then restart the app.
