# staging.sharebucketlist.com — one-time setup

Staging (site roadmap R16) runs on the same server as production, as its own service, database and
folder, behind a password, with a disguised copy of production refreshed nightly. Mail never leaves
it. James runs these steps (they need sudo); the DNS record already exists.

## 1. Code, folders and virtualenv

```bash
sudo mkdir -p /var/www/travel_site_staging && sudo chown www-data:www-data /var/www/travel_site_staging
sudo chmod 2775 /var/www/travel_site_staging
# Clone with the same address production pulls from (git -C /var/www/travel_site remote -v);
# james has no GitHub SSH key on the server, so the git@github.com address is refused.
git clone "$(git -C /var/www/travel_site remote get-url origin)" /var/www/travel_site_staging \
  || git clone /var/www/travel_site /var/www/travel_site_staging   # else from production's checkout
git config --global --add safe.directory /var/www/travel_site_staging   # the folder is owned by www-data
cd /var/www/travel_site_staging
git remote set-url origin "$(git -C /var/www/travel_site remote get-url origin)"
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p uploads private_uploads && chmod 2770 private_uploads
```

## 2. Database

```bash
sudo -u postgres psql -c "CREATE ROLE travel_site_staging LOGIN PASSWORD '<a new password>';"
sudo -u postgres psql -c "CREATE DATABASE travel_site_staging OWNER travel_site_staging;"
```

## 3. `.env`

Copy production's and change what differs:

```bash
cp /var/www/travel_site/.env .env && chmod 640 .env && sudo chown www-data:www-data .env
```

| Setting | Staging value |
| --- | --- |
| `DJANGO_SECRET_KEY` | a **new** one: `python3 -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `DJANGO_ALLOWED_HOSTS` | `staging.sharebucketlist.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://staging.sharebucketlist.com` |
| `SITE_URL` | `https://staging.sharebucketlist.com` |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `travel_site_staging` / `travel_site_staging` / the password from step 2 |
| `STAGING_BASIC_AUTH` | `staging:<the password from step 4>` (only the deploy script's live check reads it) |
| `DJANGO_ADMINS` | blank (staging errors go to the journal) |

Mail settings can stay: `config.settings.staging` never sends.

## 4. Password in front of the site

```bash
sudo apt install apache2-utils     # for htpasswd, if missing
sudo htpasswd -c /etc/nginx/staging.htpasswd staging
```

## 5. nginx, certificate, service

```bash
sudo cp deploy/staging/nginx-staging.conf /etc/nginx/sites-available/staging.sharebucketlist.com
sudo ln -s /etc/nginx/sites-available/staging.sharebucketlist.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d staging.sharebucketlist.com
sudo cp deploy/staging/travel_site_staging.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable travel_site_staging
```

## 6. First copy and first deploy

```bash
bash /var/www/travel_site_staging/scripts/sync_staging_from_prod.sh     # copies production, disguised
bash /var/www/travel_site_staging/scripts/deploy_staging.sh main        # starts the service and checks it
tail -1 ~/backups/staging_sync.log                                       # "ok: … all disguised"
```

Open https://staging.sharebucketlist.com: the browser asks for a username and password first — type
**`staging`** and the step 4 password (not your site account). Then the site's own Log in page takes
your **username** (or `user<your id>@staging.invalid`) and your normal password. The yellow bar says
it's staging. `STAGING_BASIC_AUTH` in `.env` must be `staging:<that password>`, colon included.

## 7. Nightly refresh

Add to james's crontab (`crontab -e`), after the production backups have run:

```
15 5 * * * bash /var/www/travel_site_staging/scripts/sync_staging_from_prod.sh
```

## Day to day

- Try a branch before it reaches `main`: `bash /var/www/travel_site_staging/scripts/deploy_staging.sh r17-my-branch`
- Back to main: `bash /var/www/travel_site_staging/scripts/deploy_staging.sh`
- Logs: `journalctl -u travel_site_staging -f` (emails staging "sends" appear here too); sync history in `~/backups/staging_sync.log`.
