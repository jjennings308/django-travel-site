# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Layout:** Django apps live under `apps/` and are imported as `apps.<name>` (Phase 3.5).
> App *labels* (`trips`, `accounts`, …) are unchanged, so model references (`"trips.Trip"`),
> permissions, URL namespaces and template names use the bare name.

## Project

ShareBucketList (`SITE_NAME` in settings): a Django 6 travel site for bucket lists, trips, activities and locations. It uses PostgreSQL and server-rendered templates styled with Tailwind via `django-tailwind`. The site moved from Bootstrap to Tailwind.

## Repository layout

```
manage.py
config/            # settings/{base,dev,prod}.py, urls.py, wsgi.py — not an app, stays at the root
theme/             # django-tailwind app (TAILWIND_APP_NAME = "theme") — stays at the root
apps/              # every project Django app; apps/__init__.py makes it a package
  core/ accounts/ notifications/ media_app/ approval_system/ rewards/
  locations/ activities/ vendors/ events/
  bucketlists/ trips/ reviews/ recommendations/
  pages/ admin_tools/
templates/         # site shell only: base.html, base_marketing.html, partials/, components/
scripts/           # check_layers.py, reset_db.sh, sync_dev_from_prod.sh, backup_prod.sh, restore_check.sh, lib/
docs/              # architecture diagrams
staticfiles/       # collectstatic output (git-ignored; built on each machine)
private_uploads/   # private uploads (role-request documents), outside MEDIA_ROOT; git-ignored
```

Nothing that is a Django app (has an `apps.py`) belongs at the root except `config` and `theme`.

## Commands

The virtualenv is at `.venv/`. `manage.py` uses `config.settings.dev` by default. Production uses `DJANGO_SETTINGS_MODULE=config.settings.prod`.

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt    # dev: requirements.txt + django-tailwind, browser-reload

python manage.py runserver
python manage.py tailwind start         # Tailwind watcher (theme/static_src, npm run dev) — dev settings only
python manage.py tailwind build         # production CSS -> theme/static/css/dist/styles.css
python manage.py collectstatic          # -> staticfiles/ (git-ignored build output)

python manage.py makemigrations <label> && python manage.py migrate   # label, e.g. "trips"
python manage.py test                   # all apps
python manage.py test apps.locations    # one app (test labels are module paths)
python manage.py test apps.locations.tests.SomeTestCase.test_method   # single test
```

`trips` (from the itinerary merge), `core` (layer check), `accounts` and `pages` have tests, each as a `tests/` package; the other apps' `tests.py` files are empty stubs. New tests should follow the `trips` pattern — a `tests/` package per
app, Django's built-in runner, no pytest. When patching, mock the full module path
(`mock.patch("apps.trips.views.something")`).

**Adding a new app:**

```bash
mkdir apps/<name>
python manage.py startapp <name> apps/<name>
```

Then, in `apps/<name>/apps.py`, set `name = "apps.<name>"` and pin `label = "<name>"`
(`startapp` writes only `name = "<name>"`, which is wrong here). Add `"apps.<name>"` to
`INSTALLED_APPS` in `config/settings/base.py`, put its templates in
`apps/<name>/templates/<name>/`, and add it to the layer table below and to `LAYERS` in
`scripts/check_layers.py`. Never add `apps/` to `sys.path` to shorten imports.

**Database:** Postgres runs in a Docker container named `postgres`. Connection settings come from `.env` (see `.env.example`), which `config/settings/base.py` loads with python-dotenv. To reset the database (it takes a backup to `~/db_backups` first):

```bash
set -a; source .env; set +a
./scripts/reset_db.sh [db_name] [db_user] [pg_container]
python manage.py migrate
```

**Dev data is a nightly copy of production.** `scripts/sync_dev_from_prod.sh` dumps production over SSH (read-only there), checks the dump, backs up dev, restores into the dev container, runs `migrate` (re-applies migrations not yet on production), copies new `uploads/` (add-only), compares row counts and prunes its own dumps after 14 days (`~/db_backups/travel_site_{prod,dev_pre_sync}_*.dump`); one line per run in `~/db_backups/sync.log`. It skips while a `manage.py test` run is going. Scheduled by the systemd user timer in `deploy/dev/` (03:30, `Persistent=true`): install with `cp deploy/dev/sbl-dev-sync.* ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now sbl-dev-sync.timer`; run now with `systemctl --user start sbl-dev-sync`; history in `journalctl --user -u sbl-dev-sync`. `loginctl enable-linger james` lets it run while logged out. So anything done only in the dev database is gone the next morning; this is a dev convenience, not a production backup.

**Production backups** (site roadmap R2) live on the homelab machine popsicletoes.us, not here: `scripts/backup_prod.sh` (daily 02:30, user timer `deploy/backup/sbl-backup.*`) dumps production over SSH (read-only), checks the dump, and keeps `~/backups/sharebucketlist/db/YYYY-MM-DD.dump` plus `files/YYYY-MM-DD/{uploads,private_uploads}` rsync snapshots hard-linked to the day before; retention 14 daily / 8 weekly / 12 monthly (`sbl_keep` in `scripts/lib/sbl_common.sh`, tested by `apps.core.tests.test_backup_scripts`); `--check` verifies the machine's prerequisites. Shared helpers (`log`, `fail`, `envval`, `sbl_ssh`, `sbl_dump_prod`) are in `scripts/lib/sbl_common.sh`, used by both scripts. **Restore drill** monthly on the dev machine: `scripts/restore_check.sh <dump>` (throwaway `postgres:17` container, `migrate --check`, row counts; POSTGRES_* in the environment win over `.env`, so dev is never touched). Set-up and restore steps: `scripts/README.md`. No off-site copy yet (decided 2026-10-18).

**Seed reference data** with the idempotent management commands in `apps/locations/management/commands/`. Run them in dependency order: `import_countries`, then `import_regions`, then `import_cities`, then `import_national_parks` / `import_sports_venues`, then `populate_flag_emojis`. Imported rows are marked approved automatically.

## Testing
- `manage.py test` uses `config/settings/test.py` (when `DJANGO_SETTINGS_MODULE` isn't set): MD5 password
  hashing (the real hasher made each test that creates accounts take seconds), locmem email, geocoding off,
  no dev-only apps. The full parallel run takes about 70 seconds (was ~11½ minutes before R12).
- **CI** (`.github/workflows/test.yml`, site roadmap R12) runs on every push to `main` and on pull requests into
  it (R23, for Dependabot): `pip-audit -r requirements.txt` (fails on any known vulnerability; an unfixable one
  goes in `.pip-audit-ignore`, one ID per line with a `#` reason), layer check, `makemigrations --check`,
  `check --deploy` with dummy production env, the full suite on a fresh Postgres 17, and a check that the
  committed Tailwind CSS matches a fresh `tailwind build`. A failure emails the pusher; `gh run list` /
  `gh run watch` show it from here. **Dependabot** (`.github/dependabot.yml`) opens one grouped PR a month for
  the pip pins and one for the Actions versions.
- **Timing:** `manage.py perf_report [--trip <pk>] [--runs 3]` (R23, `apps/pages`) prints queries and median ms
  for the trip page, Settings, Bookings, the booklet (HTML / PDF), the calendar feed, search, the events calendar, the
  sitemap and a city page + What's on, rendered as a staff user inside a rolled-back transaction (nothing
  saved). Run it on dev's copy of production before and after a performance change.
- Always run tests with `--keepdb` and `--noinput`.
- While iterating on a change, run only the affected app's tests:
  `.venv/bin/python manage.py test apps.<app> --keepdb --noinput`
- Before finishing a task, run the full suite in parallel:
  `.venv/bin/python manage.py test --keepdb --parallel --noinput`
- If a test fails only under `--parallel`, report it as a test-isolation
  bug rather than dropping the flag.
- After adding a migration, drop the parallel test copies (`test_travel_site_1` … `_N`) or run once
  without `--keepdb`: `--keepdb` migrates the main test database but reuses existing copies as they
  are, so the parallel run fails on missing columns (seen with trips 0032).
- A test that needs real transactions (stepping migrations back and forth) subclasses
  `apps.core.testing.RestoringTransactionTestCase`, never plain `TransactionTestCase`: a plain one
  empties every table when it ends, including rows data migrations seeded (place types, notification
  kinds), and with `--keepdb` the emptied parallel copies break the next run.
- A migration test that steps an app back (e.g. `trips` to 0022) must also pin every *other* app whose
  newer migrations need that app's newer state — today `rewards` (0003 runs after trips 0042) and `reviews`
  (0004 depends on today's trips); and one that steps `activities` back must pin `trips` (0043: trips 0044 needs
  today's activities and locations), and one that steps `locations`, `activities` or `events` back must pin
  `catalogue_notes` to zero (`("catalogue_notes", None)`: its 0001 needs today's catalogue) — or the old state can't be reached and the test errors (and a failed
  migration test can leave the parallel copies half-migrated, which hangs the next parallel run: drop
  every `test_travel_site*` database and rerun).
- `tblib` (in `requirements-dev.txt`) lets the parallel runner report a failing test's traceback;
  without it the run dies with "cannot pickle 'traceback' object" and hides which test failed.

## Deploying (staging / production)

`config.settings.prod` refuses to start without a real `DJANGO_SECRET_KEY` (≥ 50 chars, not
`django-insecure…`) and `DJANGO_ALLOWED_HOSTS`. It assumes nginx terminates TLS and sets
`X-Forwarded-Proto` (`SECURE_PROXY_SSL_HEADER`), redirects to HTTPS, uses secure cookies, sets
HSTS to a year (`SECURE_HSTS_SECONDS`, default 31536000; use 3600 on a brand-new domain) and logs to stderr (systemd journal).
`security.W005` / `W021` (HSTS subdomains/preload) are silenced on purpose until HTTPS is proven on
the real domain. `django-browser-reload` is dev-only (`dev.py`; not in `requirements.txt`), and its
`/__reload__/` URLs exist only when it is installed.

**Error emails and health** (site roadmap R3): `DJANGO_ADMINS` in `.env` (`James <j@…>, …`; parsed by
`apps.core.settings_helpers.parse_admins` into `ADMINS`; empty = off; sender `SERVER_EMAIL`) receives
`django.request` errors through `apps.core.alerts.AlertEmailHandler` (prod.py `LOGGING`), never Django's
`AdminEmailHandler`: subject = exception type + innermost file:line, body = method, path (no query
string), user id, time and the traceback **without** locals — no POST data, cookies, headers or settings
(forms hold passport and loyalty numbers). One email per distinct error per hour; repeats go only to the
journal and the next email says "+N more" (counts in the `alerts` FileBasedCache in `/tmp`, shared by the
gunicorn workers). `/healthz/` (`apps.core.health`, name `healthz`): 200 `ok` when `SELECT 1` works and
the static manifest resolves `css/dist/styles.css`, else 503 `unavailable` (reason logged as a warning,
never mailed); plain text, no login, `no-store`. `deploy.sh`'s live check requires it; James's uptime
monitor watches it.

**Visit statistics:** the shared box's self-hosted Umami (`analytics.tazcomputer.com`, cookieless) via
`templates/partials/_analytics.html` in both bases. `ANALYTICS_SCRIPT_URL` / `ANALYTICS_WEBSITE_ID` are empty in
`base.py` (dev and tests never count), filled in by `prod.py` and emptied again by `staging.py`. No SRI (our own
server; its script changes with Umami upgrades — the upkeep SRI test skips template-variable URLs); query strings
and fragments aren't sent, Do Not Track is honoured, and addresses holding a secret (`core.context_processors.ANALYTICS_SKIP`:
shared trips, invites, password reset, email verification, unsubscribe) get no script — add any new token URL there.
The privacy page's section 5 describes it.

**Live:** https://sharebucketlist.com on `james@tazcomputer.com` (shared Debian 13 box that also hosts
soho, score, tazcomputer, umami, excalidraw). Repo at `/var/www/travel_site` (owner www-data,
group-writable; `james` is in group www-data), gunicorn 2 workers as `travel_site.service` on
`/run/travel_site/travel_site.sock`, nginx site `/etc/nginx/sites-available/sharebucketlist.com`
(certbot TLS, `www` -> apex), Postgres 17 database/role `travel_site` on 127.0.0.1, outbound mail
via smtp2go. `sudo` there needs a password, so service/nginx changes are run by James.

**Staging** (site roadmap R16): https://staging.sharebucketlist.com on the same server — `config.settings.staging`
(prod settings; mail goes to the console, never out; a yellow staging bar; `X-Robots-Tag: noindex`; its own
`/tmp` cache folders), service `travel_site_staging` (1 worker), folder `/var/www/travel_site_staging`, database and
role `travel_site_staging`, nginx with **basic auth** over the whole site (`deploy/staging/`; setup in its
README). `scripts/sync_staging_from_prod.sh` (James's crontab, nightly) restores production into it and runs
`scripts/staging_disguise.sql` (emails → `user<id>@staging.invalid`, phones and travel-document numbers blanked,
contact/invite emails disguised; no `private_uploads`), then refuses to finish if any real email is left.
`bash /var/www/travel_site_staging/scripts/deploy_staging.sh [branch]` puts a branch on staging through the same
`deploy.sh` (which reads `SBL_APP` / `SBL_SITE` / `SBL_SETTINGS` / `SBL_SERVICE` / `SBL_CURL_AUTH`, defaulting to
production). Sign in there as `user<id>@staging.invalid` with your usual password.

**Deploying an update:** push to `main`, then on the server `bash /var/www/travel_site/scripts/deploy.sh`
(asks for sudo first, then pull, requirements, `check --deploy`, `pg_dump` + migrate when migrations are
pending, `collectstatic` **without** `--clear` so the still-running app keeps its old hashed files,
restart, a live check that exits 1 if the home page or stylesheet isn't 200, then prunes hashed static
files the manifest no longer uses once they're a week old). A `--clear` before a restart that never
happened once left the site unstyled. Production uses `ManifestStaticFilesStorage`:
CSS/JS are served under content-hashed names, so a restart after `collectstatic` is required and a
`{% static %}` path that doesn't exist is a 500 (not a broken image) — check new static references
exist. `staticfiles/` is build output and is not committed; never rely on files that exist only there.

First-time setup on a fresh Debian box (repo at `/var/www/travel_site`, where `manage.py` is):

```bash
git clone git@github.com:jjennings308/django-travel-site.git /var/www/travel_site && cd /var/www/travel_site
cp .env.example .env        # set DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS,
                            # SITE_URL, DJANGO_DEBUG=False, POSTGRES_*, EMAIL_* (that box's SMTP provider)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo chown www-data:www-data .env uploads
export DJANGO_SETTINGS_MODULE=config.settings.prod
.venv/bin/python manage.py check --deploy && .venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo cp deploy/travel_site.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now travel_site
sudo cp deploy/nginx-travel_site.conf /etc/nginx/sites-available/travel_site   # edit server_name/certs, symlink, nginx -t, reload
```

The built Tailwind CSS is committed and gathered by `collectstatic` from the `theme` app. Production cannot rebuild it: the `tailwind` app is installed only in `dev.py` and `django-tailwind` is only in `requirements-dev.txt`, so `manage.py tailwind …` does not exist there and the box needs no Node. Always run `tailwind build` in dev and commit `theme/static/css/dist/styles.css` with any template or CSS change. Verify with
`DJANGO_SETTINGS_MODULE=config.settings.prod python manage.py check --deploy` (expect "no issues (2 silenced)").

## Architecture

### Settings and URLs
- `config/settings/{base,dev,prod}.py`. `base.py` reads env vars, including all outgoing-mail settings (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`/`EMAIL_USE_SSL`, `EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`); the provider differs per machine, so never hard-code it, and never put credentials in settings files. `dev.py` and `prod.py` override `DEBUG`, `ALLOWED_HOSTS`, `SITE_URL` and `EMAIL_BACKEND`.
- `config/urls.py` mounts each app under its own namespace (`pages:` for home/dashboard/about, `locations:`, `activities:`, `trips:`, `bucketlists:`, `events:`, `rewards:`, `staff:`) with `include("apps.<name>.urls")`. Use namespaced names with `reverse` and `{% url %}`. `apps.accounts.urls` (login, register and so on) is not namespaced. Staff-only views live in `apps/accounts/staff_urls.py` under `/staff/`. `/staff/` itself is the **staff dashboard** (`pages:staff_dashboard`, `apps/pages/staff.py`, gated by `User.can_access_staff`, linked from the header user menu): site stats plus a "needs attention" list (pending approvals vs the `ApprovalSettings.review_sla_hours` target, role requests, events with an unlisted city, cities missing a region, yearly activities with no upcoming event, unlinked activity places, leftover HEIC media, placeholder emails, legal placeholders). Add new staff to-dos there as another entry in `_attention()`. **CSV import/export** (`/staff/import/`, `admin_tools:import`, same gate): upload countries, regions, cities, places (POIs), activities or events (in that order; each looks up the earlier ones) → preview (new / update / error per row, nothing saved) → confirm; templates at `admin_tools:import_template`; `admin_tools:export` (and `manage.py export_catalogue [dir]`) writes the published items in the same columns, so an export can be edited and re-imported. `apps/admin_tools/importers.py` describes each kind once in `KINDS` and maps columns to the normal `ActivityEditForm` / `EventForm` (locations use small model forms there) (names looked up for category, country, region, city, activity) so imports obey the same validation; an activity matches by name, an event by name + start date, a country by ISO code, a region by name within its country, a city by name + region within its country (cities are unique per region — `city_unique_name_region_country`, so Kansas City MO and KS both exist; a same-named city needs the `region` column, and a row naming a region fills it in on a region-less match; new city slugs carry the region code, `kansas-city-ks-us`), a place by name within its city (ignoring capitals), and blank cells keep existing values. An event city not in the catalogue becomes a typed town. Imported rows are published (activity `source="import"`). The upload waits in the session between preview and confirm. **Dates in these CSVs are `m/d/yyyy`** (rule added 2026-10-23: `9/18/2027`, no leading zeros — what Excel shows and opens as a date in a US locale): export writes them that way, the templates' example rows use them, and the error says "use M/D/YYYY"; import still also accepts `yyyy-mm-dd` and the other `DATE_FORMATS`, so older exports re-import. Never accept `d/m/yyyy`. Times stay `20:00` / `8:00 PM`. Converted 2026-10-23 (`importers.DATE_FORMATS` lists M/D/YYYY first; `test_import` checks export, template and the refused day-first date; the import page and `running-the-site` say so).
- `AUTH_USER_MODEL = 'accounts.User'` (a label reference — no `apps.` prefix). Login accepts a username or an email (`apps.accounts.backends.EmailOrUsernameBackend`).
- Settings that hold **module paths** (`INSTALLED_APPS`, `MIDDLEWARE`, `TEMPLATES` context processors, `AUTHENTICATION_BACKENDS`, logging handlers) use `apps.<name>.…`. Settings that hold **labels** (`AUTH_USER_MODEL`, `"label.Model"` strings, permission strings like `"accounts.can_access_staff_dashboard"`) do not.

### Private files
Uploads that must not be public (role-request `supporting_documents`) use `apps.core.storage.private_storage` (root `PRIVATE_MEDIA_ROOT` = `private_uploads/`, outside `MEDIA_ROOT`, so nginx's `/media/` never serves them; no `.url`). They are downloaded through access-checked views (`role_request_document`: the requester and staff, 404 otherwise). `deploy.sh` creates `private_uploads/` with mode 2770. Any new sensitive upload should use the same storage and a view. The `ui_theme` cookie is HttpOnly, SameSite=Lax and Secure over HTTPS. `deploy/` holds the live nginx site and systemd unit (2 workers).

### Shared base models (`apps/core/models.py`)
App models are built from abstract mixins: `TimeStampedModel`, `UUIDModel`, `SlugMixin`, `SoftDeleteModel`, `PublishableModel`, `FeaturedContentMixin`. Generate slugs with `apps.core.utils.generate_unique_slug`. Other helpers under `apps/core/utils/` handle breadcrumbs, currency, imperial/metric conversion and age. **HEIC/HEIF:** `pillow-heif` is registered in `CoreConfig.ready()`, and `apps/core/signals.py` (a `pre_save` on every model, via `apps.core.utils.images.convert_heic_uploads`) stores any newly uploaded `.heic`/`.heif` file as JPEG — upright, metadata (incl. GPS) dropped — because only Safari displays HEIC. `Media.save()` converts first so its size/extension/MIME describe the JPEG. `docs/architecture/` has Mermaid diagrams of the intended app-dependency direction and FK ownership. Check them before adding cross-app foreign keys.

### Approval / moderation (`approval_system`)
User-submitted content inherits the `apps.approval_system.models.Approvable` mixin. It adds `approval_status`, priority, submitted/reviewed-by fields and an `ApprovalLog` audit trail. Admin classes add `ApprovableAdminMixin`. When filtering for public visibility, use `approval_status=ApprovalStatus.APPROVED`.
- `locations` models (Country, Region, City, POI) still carry the old `ReviewableMixin` (`status` field) next to `Approvable`. A migration from the old system is in progress (see `apps/approval_system/MIGRATION_GUIDE.md`). New code should use the `Approvable` fields. Both mixins define `approve()` / `reject()` / `request_changes()` and `ReviewableMixin` comes first in the MRO, so its versions set the legacy `status` and then call `super()` to reach `Approvable` (which owns `approval_status` and `ApprovalLog`). Keep that `super()` call, or approvals silently stop moving locations out of the pending queue.
- `Activity` also uses `Approvable`. App-level docs are in `apps/approval_system/*.md` and `apps/accounts/docs/`.
- **Catalogue notes** (`apps/catalogue_notes`, layer 3 after `events`; plan `docs/plans/catalogue-notes.md`): a
  `CatalogueNote` (`Approvable`; exactly one of `poi` / `activity` / `event`, `catalogue_note_one_target`; tone tip /
  warning / critical, text, `closed_weekdays` (0 = Monday), `book_ahead` + `book_ahead_unit`, `booking_url`,
  `checked_on`) is a fact a traveller should know about a place, activity or event. Members' notes are pending until
  approved in the "Catalogue notes" queue (catalogue_notes 0002); staff's are published. `services.notes_for(target,
  user)`: own, then inherited — an event's activity and venue (`Event.poi`), an activity's venue — each inherited one
  marked `from_name`; approved for everyone, plus a member's own pending ones, everything for staff. The **Good to
  know** card on place / activity / event pages is the shell partial `partials/_catalogue_notes.html` (loads
  `catalogue_notes:for_target` after the page, as reviews do, so the catalogue apps never import it); add / edit /
  delete (writer until approved, staff always) and report ("Out of date?", `content_reported` to staff). Listed in the
  staff dashboard's approvals; `/notes/` is disallowed in robots.txt.
- **Lifecycle:** an *activity* is an undated idea ("Go to Oktoberfest") with an optional catalogue place (`country` / `region` / `city`; a city fills in the other two on save; `suggested_location` is free text for unlisted places, `place_name` renders either) and `recurrence` (anytime / yearly / seasonal / once) plus `usual_months`. A recurring activity has **one event per occurrence** (Oktoberfest 2026, Oktoberfest 2027), never one repeating event: each year has its own dates, prices, approval, bucket items and trips (`Event.is_recurring` is unused). On an event of a yearly activity, "Add <next year> dates" opens `/events/add/?copy=<pk>` with the dates moved a year on (or links next year's event if it exists); for a several-times-a-year (`seasonal`) activity such as a team's home games it is "Add another date" (`?copy=<pk>&another=1`: same details, date blank) — `events.views._next_date_link`. An activity may name a `venue` (a POI; fills in its city), events have `poi` as their venue (on `EventForm`, pre-filled from the activity), and the CSV import has activity `venue` / event `place` columns. The activity page's Dates card groups events by season (`Activity.dates_by_season` / `season_label`: when `usual_months` wraps New Year a January game belongs to the season that started the autumn before, "2026–27") with past dates folded away. The region/city selects are filtered by country in the browser by `locations/country_filter.js` + `apps.locations.widgets.CountryTaggedSelect` (also used by the city admin). An *event* is a dated occurrence of it (`Event.related_activity`, e.g. Oktoberfest 2027; `/events/?activity=<slug>` lists an activity's dates and `/events/add/?activity=<pk>` pre-fills one); a *trip* is the plan for going. Activities and events share ONE category list (`activities.ActivityCategory`; `EventCategory` was removed in events 0005/0006, which copied categories across by name). An event with no category takes its activity's. The activity page links to its dates via the shell partial `partials/_activity_dates_links.html` (`url … as`), so activities doesn't depend on events.
- **One look for activities and events:** detail pages use the shared `partials/_detail_header.html` (banner with picture or clay background, category, title, date/recurrence and place, approval badge with a one-line explanation) and the same layout (sections left; Quick Info and Actions cards right); list pages (`activity_list`, `my_activities`, `event_list`, `my_events`) use the shared `partials/_catalogue_card.html`. Change both through those partials. (`my_activities.html` used to be a symlink to `activity_list.html`; it is a real template now.)
- **Pictures:** activities and events have an optional `featured_media` (FK to `media_app.Media`, like places). Their forms use `apps.media_app.forms.PictureFormMixin` (`setup_picture()` in `__init__`, `save_picture(user)` after save; views pass `request.FILES`, templates use `enctype="multipart/form-data"` and `partials/_picture_field.html`): an upload becomes a `Media` row attached to the object, scaled to at most 2400 px (`apps.core.utils.images.shrink_image`), max 20 MB (nginx allows 25). A new event of an activity starts with the activity's picture (`Event.save()` on create, so the form, CSV import and admin all do it; the same `Media` row), and an event copied to next year keeps last year's picture instead; either is replaced for that event only by uploading one (or removed with "Remove the current picture"). **Shown picture:** templates use `display_media`, never `featured_media`, for activities and events: their own picture, else (events) the activity's, else the place's — venue, city, region, country (`PICTURE_PATHS`, walked by `apps.media_app.pictures.first_media`, images only). List views `select_related(*Model.PICTURE_RELATED)` so cards cost no extra query; edit forms still show only the object's own picture.
- `Event` uses `Approvable` too, plus `created_by`. Users submit events at `/events/add/` (staff publish directly); a submission is `pending` and visible only to its creator and staff (`Event.objects.visible_to(user)` / `event.is_visible_to(user)`, 404 otherwise) until approved in the "Events" approval queue (seeded by `events` migration 0003, with starter `EventCategory` rows). Creators can edit/delete until approval; editing a rejected or changes-requested event re-submits it.

### Users, roles and per-user settings
- **Sign-up** (site roadmap R14): `SIGNUP_MODE` (`.env`, default `invite`; `open` lets anyone register).
  In invite mode `accounts.views.register` needs a usable `accounts.SignupCode` (`?code=` / the form's
  `signup_code`; made in the admin, each sign-up uses one) or the session key `signup_allowed_until`, which
  the trips invite page sets for a signed-out visitor holding an open invite (a string contract — neither
  app imports the other); otherwise `accounts/register_closed.html`. Staff creating accounts are exempt.
  The sign-up form no longer has role boxes; Settings links **Request a role**. The dashboard's first-run
  **welcome** (`pages.views._welcome`: add a goal, start a trip, invite someone; hidden when all done or with
  Hide this → `User.welcome_dismissed_at`) links the `getting-started` guide.
- Roles are Django Groups: `Vendors` and `Content Providers`. Users request a role through `accounts.RoleRequest`, and approving the request adds them to the group. Staff access uses the `accounts.can_access_staff_dashboard` permission. Check access with the `User` properties `is_vendor`, `can_access_staff` and `can_access_*_dashboard`.
- Per-user data is spread over `Profile`, `AccountSettings` (`user.settings`: units, currency, language, timezone, theme) and `TravelPreferences` (`user.travel_preferences`). `UserPreferences` is the older combined model and was split into these.
- Request-time plumbing:
  - `apps.core.middleware.UserTimezoneMiddleware` activates the zone chosen in Settings (`AccountSettings.timezone`,
    `user.settings` — the row UserThemeMiddleware also reads, so one query). Until R21 it read the deprecated
    `UserPreferences`, which nobody has, so every reader was UTC.
  - `UserThemeMiddleware` sets `request.theme` and the `ui_theme` cookie.
  - Context processors in `apps/core/context_processors.py` expose `user_units`, `user_currency`, `user_theme`, `user_travel_styles` and similar to every template.
  - `apps/core/templatetags/conversion_tags.py` provides unit and currency filters that use these values (`{% load conversion_tags %}` — tag libraries load by name, not path).

### Templates and styling
- Site-level templates are in `templates/`: `base.html` (Tailwind app shell with header, sidebar and messages), `base_marketing.html` (public pages), `partials/` and `components/`. App templates extend `base.html`. Reusable pieces are included with `{% include 'components/cards/stat_card.html' with color="clay" ... %}`; see `templates/components/README.md`.
- App templates live in `apps/<name>/templates/<name>/` and are still referenced as `"<name>/…html"` (e.g. `trips/trip_detail.html`); the `apps/` directory never appears in a template name.
- Detail and list views pass `breadcrumb_list` (built with `apps.core.utils.breadcrumbs`); templates fill `{% block breadcrumbs %}{% include "partials/_breadcrumbs.html" with breadcrumbs=breadcrumb_list %}{% endblock %}`, which `base.html` renders above the messages. Paginated lists use `{% include "partials/_pagination.html" %}` (needs `page_obj`; `{% querystring %}` keeps the filters).
- **Bootstrap is not loaded.** `base.html` dropped Bootstrap's CSS/JS in `ddd00d7`; any template still using its classes (`row`/`col-*`, `btn`, `card`, `list-group`, `badge bg-*`, `form-control`, `data-bs-*`) renders unstyled. Convert to Tailwind plus the shared `sbl-*` components in `styles.css` (`sbl-card`, `sbl-btn` + `-primary`/`-secondary`/`-accent`/`-danger`/`-outline`, `sbl-input`, `sbl-label`, `sbl-badge-*`, `sbl-alert-*`, `sbl-list`, `sbl-table`, `sbl-page-title`). Interactive bits use Alpine.js (loaded in `base.html`). All live templates are converted (site shell, `pages`, `locations`, `accounts`, `rewards`, `activities`); form widgets set `sbl-input` / `sbl-check` in `forms.py`. The unused Bootstrap-era templates were deleted.
- Tailwind source is `theme/static_src/src/styles.css`, using Tailwind v4 (`@import "tailwindcss"`) with the **typography** plugin loaded (`@plugin "@tailwindcss/typography"`, for the Help guides' `prose`). The forms plugin and DaisyUI are in `package.json` but deliberately not loaded (forms would restyle every input on the site). `@source` globs cover `templates/` and `apps/*/templates/`; the brand palette is a `@theme` block (`earth-*`, `warm-*`, and `accent-*` = clay, which the trips components use). `tailwind.config.js` is ignored by v4. The old hand-written `!important` utility block is gone (it overrode every `hover:`/responsive variant); don't add `!important` utilities back. The built `theme/static/css/dist/styles.css` is committed: rebuild with `python manage.py tailwind build` (dev only) after template or CSS changes. `base.html` / `base_marketing.html` link it with `{% static 'css/dist/styles.css' %}` (not django-tailwind's `{% tailwind_css %}` tag, so production needs no tailwind app); in DEBUG a `?v=` from the `site_branding` context processor defeats browser caching.
- **Trips pages are scoped.** Every trips template extends `trips/base_trips.html`, which sets `content_class` = `trips-ui` (and a default `wrap_class` width) on `base.html`'s content area. The itinerary component layer (`.card`, `.btn`, `.badge-*`, `.callout-*`, `.chip`, form controls) and its `@media print` rules are written as `.trips-ui …` in `styles.css`, so they never restyle other apps' templates. Tests assert those class names. Site header, sidebars and footer carry `print:hidden`.
- Icons: Bootstrap Icons (`bi bi-*`) and flag-icons, both loaded from a CDN.
- **CDN files are pinned with SRI** (R23): every external `<script src>` / stylesheet `<link>` names an exact
  version and carries `integrity="sha384-…"` (or sha512) and `crossorigin="anonymous"` — Alpine 3.17.4, Bootstrap
  Icons 1.11.0, flag-icons 7.2.3 (npm path), Leaflet; `apps/pages/tests/test_upkeep` fails otherwise. To update
  one: change the version, hash the exact file (`curl -s URL | openssl dgst -sha384 -binary | openssl base64 -A`)
  and, since the offline worker caches CDN files, bump the cache name in `core/sw.js` **and**
  `trips/partials/_offline.html` (`sbl-offline-v2-` → `v3`; a test checks they match). Dependabot doesn't cover them.
- **Settings' selects** (was Edit trip) load each option list once per page (`trips.forms.share_choices`, R23; a
  ModelChoiceField re-queries on every render), so the page's count doesn't grow with rows
  (`test_upkeep.EditTripQueryTests`, pinned at 19; 60 with the formsets before edit-by-day E3, 23 with All stays &
  legs, which moved to Bookings in day-first P7).
- **Dates and times on forms always use the browser's pickers** (rule added 2026-10-23). Every form field
  that takes a date, a time or a date-and-time — model forms, plain forms, formsets, fields added in
  `__init__` — renders as a native picker, never a plain text box:
  - date → `<input type="date">`, value format `%Y-%m-%d`;
  - time → `<input type="time">`, format `%H:%M` (no seconds);
  - date and time in one value → `<input type="datetime-local">`, format `%Y-%m-%dT%H:%M`.
    Trip leg times (`LocalDateTimeField`, incl. the return trip's) use this widget for the wall-clock time
    and keep their zone select beside it; the field's lenient parser stays, so older typed formats and an
    explicit offset still parse.
  - A model that stores date and time separately (an event's `start_date` + `start_time`) gets two inputs
    side by side, not one `datetime-local`.
  Use the shared widgets in `apps/core/widgets.py` (`DateInput`, `TimeInput`, `DateTimeLocalInput`, which
  set the type, the format and the site's input class) rather than repeating `attrs={"type": "date"}`.
  Free-text "when" fields that aren't dates stay text (`BookingTask.due_note`, `target_season`, "mid-morning"
  in narrative). The Django admin keeps its own date widgets. `apps/core/tests/test_date_pickers.py` imports
  every `apps/*/forms.py`, builds each form (with the arguments its tests use, else from `base_fields`) and
  fails on any date / time / datetime field whose widget isn't one of these; a deliberate exception goes in
  its allow-list with a one-line reason. Converted 2026-10-23: every form uses them (trip forms with `styled=False`, since `.trips-ui` styles inputs by type); `LocalDateTimeField` renders `datetime-local` and seeds `2026-01-15T18:00`; the admin's own forms (`DayAdminForm`, `LodgingAdminForm`, `TransportLegAdminForm` date fields) are the allow-list.
- **Phones** (site roadmap R11 phone pass, checked at 390 px): every page fits without sideways scroll —
  tables scroll inside `.scroll-x` (which is `relative`, so absolutely positioned bits inside are clipped by
  it, and bleeds only 16 px into the gutter on a phone), `fieldset { min-width: 0 }` (a fieldset's default
  min-width is its content), grid/flex cards with one-line truncated text need `min-w-0`, and long words
  wrap (`overflow-wrap: break-word` on `body`). Below `sm`, buttons, form fields, clickable chips, menu,
  footer and breadcrumb links are at least 44 px tall (the phone block at the end of `styles.css`); the
  header's icon buttons are `min-h-11 min-w-11`. Keep both when adding pages or components.
- **Bucket lists (`apps/bucketlists`):** a `BucketListItem` is the user's thread through the lifecycle, `item.stage` = idea → dated → trip → done. Its "what" is one of: an `activity`, a `city`, an `event` on its own, one or more `pois` (M2M; adding a POI makes it "an activity for them", with an optional `custom_title` as the goal's name), or a custom goal (`custom_title`); `item.kind`, `item.target`, `item.target_url` resolve it. An activity item is dated by picking one of that activity's events (`item.event`, must be `related_activity` of it); other items are dated by `target_date`/`target_end_date`. Adding an event whose activity is already on the list dates that item instead of starting a new one. "Plan a trip" (`bucketlists:plan_trip`) is open to any signed-in user, pre-fills from `item.dates`/`item.place`, creates the `Trip` with an editor grant and sets `item.trip` (the FK lives on the item, so `bucketlists` → `trips`, never the reverse); `item.live_trip` ignores soft-deleted trips. **Several goals can share one trip** (`item.trip` is a plain FK): "Plan a trip" also lists the user's current trips (overlapping dates first) to add the goal to (`bucketlists:add_to_trip`); the trip's Ideas shelf links (shell partial `partials/_trip_goals_link.html`, no query) to `bucketlists:trip_goals`, which lists the user's goals on that trip and lets them add or remove others (adding returns to the shelf); **a goal on a trip is an idea there** (day-first P6): `item.trip_idea` (bucketlists 0007, SET_NULL; `save()` sets `trip` from it) — `_attach` makes or reuses the trip's `TripIdea` about the same catalogue target (`item.idea_target()`: event, activity, city, first POI; else the title; never the personal notes), gives the owner a vote on it and `trip_cities.sync`s, but only when the user may comment (a viewer's goal gets `trip` only); 0008 made ideas for goals already on trips; `bucketlists:remove_from_trip` unlinks. Seeing the trip is enough (a traveller can attach their own goal to a family trip); it changes the goal, never the trip. Migrations 0003–0005 are hand-written (schema / data / drop `poi`) because Postgres refuses index creation after a data change in the same transaction. Items are private to their owner (other users get 404) and `is_public` defaults to False; `/bucketlists/u/<username>/` shows public items only when the owner's `profile_visibility` is `public`. Categories are per user (`item.categories`, through `BucketListItemCategory`). The "Add to bucket list" button is the shell partial `partials/_bucket_add_button.html` (`{% include … with kind="city" obj=city %}`); it uses `{% url … as %}` so catalogue apps render fine without bucketlists — keep lower-layer templates referencing it only that way. `signals.py` keeps `Activity/Event.bucket_list_count` recounted on every save and delete (old and new target, since an item can gain an activity or event after creation). **My dates** (`bucketlists:dates`, sidebar stage 3) lists the user's open goals by `item.dates`: coming up (with Plan a trip), needs a date (activity goals offer that activity's next 3 visible events, picked via `bucketlists:pick_date`), and date has passed. The sidebar (`partials/_sidebar.html`) is grouped by the lifecycle: Discover (activities, events, places) → Dream (bucket list) → Pick a date (My dates) → Plan (trips) → Done (bucket list `?status=completed`); events/activities a user *submitted* are under "My contributions" in the header user menu. Each numbered sidebar section folds (Alpine): the current page's section is always open, the others remember open/closed in `localStorage` (`sbl-nav-<name>`), open by default; Home and About never fold. "Add a goal" suggests catalogue matches as the title is typed (`bucketlists:suggest`, JSON: public activities, upcoming visible events, approved cities/POIs), and a custom goal's edit page can link it to one (`bucketlists:link_item`): status, dates, notes and categories stay, `custom_description` is appended to `personal_notes`, `custom_title` is cleared except for POI goals, and a target already on the list is refused.
- **Help center** (`docs/plans/help-center.md`): guides are markdown files in `apps/pages/help/<slug>.md`
  with a header (`title`, `summary`, `audience` = everyone / editors / staff, `section` — one of
  `helpdocs.SECTIONS` — `order`, `updated` ISO date; no other keys), then a blank line and the body
  (its leading `# Title` is dropped; `##` headings become "On this page" anchors). `apps/pages/helpdocs.py`
  parses them (Python-Markdown: tables, fenced code, toc, sane lists; tables wrapped to scroll on a
  phone; cached by file names and mtimes), `pages:help` (`/help/`) lists them by section under the five
  steps and the FAQ, and `pages:help_guide` (`/help/<slug>/`) shows one with breadcrumbs, On this page
  (3+ `##` headings), the updated date and related guides. `staff` guides are only for
  `User.can_access_staff` (404 otherwise). Guides are trusted, committed content — never secrets,
  server names or deploy steps. Adding a guide is adding a file; `apps/pages/tests/test_help.py` parses
  every guide strictly and checks every link in it (other guides and their `#anchor`s, site paths via
  `resolve`). Lower apps link to a guide only with `{% url 'pages:help_guide' 'slug' as help_url %}{% if
  help_url %}…{% endif %}` — in practice through the shell partial `partials/_help_link.html` (`with
  slug=… anchor=… label=…` gives a round "?"; add `text="How this works"` for a text link; never printed).
  The trip page has "?" by Days (`#days-at-a-glance`), Reference and Download PDF (`reading-your-trip#…`); Settings,
  the day page, the leg page, the Confirmations and Contacts & info boxes and the tidy page have "How this
  works"; the account menu has Help. `apps/pages/tests/test_help_links.py` renders those pages and checks
  every `/help/` link and anchor. **A change to a user-facing feature updates its guide in the same PR and
  bumps its `updated` date.**
- **Your data** (site roadmap R13; `pages:my_data` at `/account/data/`, linked from Settings): **download**
  (`pages:data_export`, POST, once per 10 min) streams a zip built by `apps/pages/account_data.export_zip` —
  JSON per area plus `files/` (their uploads); trips as they see them, other people by name only, never
  another person's private profile. **Delete** (password + tick) sets `User.deletion_requested_at` (accounts
  0016), signs them out and emails the date; while pending their public bucket list and profile 404 and
  `notify()` sends them no email; signing in cancels it (`pages/signals.py`, `user_logged_in`).
  `manage.py purge_deleted_accounts [--dry-run]` (daily cron on production) purges accounts asked > 30 days
  ago (`account_data.purge`): shared trips they created go to the longest-standing other editor (else the
  longest-standing member, made editor), solo trips are deleted with their photos and tickets, personal
  `Media` is deleted **with its files** (pictures used as a catalogue `featured_media` stay), the `Traveler`
  is scrubbed and unlinked (deleted if no trip uses it), the role-request document is removed, then the
  user is deleted. `Activity.created_by`, `Media.uploaded_by`, `Review.user` and `trips.Comment.author` are
  SET_NULL (R13) so catalogue items, pictures, reviews and trip notes survive as "A former member"
  (`Review.author_name`, `Comment.author_name` — use these, never `.user.username` / `.author` directly).
  The staff dashboard lists accounts scheduled for deletion. It lives in `pages` because it reaches every app.
- **Abuse guards** (site roadmap R15): `apps/core/ratelimit.py` — `limit(scope, n, seconds)` per visitor IP
  (nginx `X-Real-IP`) on log-in (10/15 min), sign-up (5/h POST), password reset (5/h), wrong sign-up codes
  (10/h, `hit()`), invite links (60/h); over it a 429 page that names no account. Counts in the `ratelimit`
  file cache in prod; `RATELIMIT_ENABLED = False` in the test settings (`test_ratelimit` turns it on). A
  hidden honeypot field `website` on sign-up fakes success. **Storage:** `apps/media_app/quota.py`
  (`STORAGE_LIMIT_MB`, 1024; staff unlimited) sums `Media.file_size` plus registered providers (trips
  registers ticket files in its `ready()`); every upload helper calls `quota.check()` *before* saving and
  `apps.media_app.middleware.QuotaMiddleware` turns `QuotaExceeded` into a message and a redirect back
  (tickets turn it into a `files.Refused`). **Unsubscribe:** `notify()` emails carry a signed per-person,
  per-kind link and `List-Unsubscribe` / `List-Unsubscribe-Post` headers → `notifications:unsubscribe`
  (csrf-exempt; token is the credential) sets `UserNotificationPreference.email_enabled`; `wants_email(user,
  kind)` honours it. **Reports:** `reports:report` (`/report/<activity|event|place>/<pk>/`, `admin_tools/reports.py`,
  the old `ReportedContent` model; link via `partials/_report_link.html`) notifies staff (`content_reported`,
  notifications 0004); three open reports on a member-submitted, approved activity or event set it back to
  pending. **Suspend:** user admin actions set inactive + `suspended_at` / `suspension_reason` (accounts 0018).
  The staff dashboard shows open reports and accounts at 80%+ of the storage limit.
- **Terms versions** (site roadmap R16): `TERMS_VERSION` / `PRIVACY_VERSION` in `base.py` — **bump the date in
  the same change that edits `terms.html` / `privacy.html`**. Sign-up records them (`User.terms_version`,
  `privacy_version`, `legal_accepted_at`; `User.accept_legal()`); `apps.accounts.middleware.LegalAcceptanceMiddleware`
  sends a signed-in GET whose versions are out of date to `accept_legal` (`/accounts/legal/`), except the
  paths in `apps/accounts/legal.EXEMPT_PREFIXES` (legal pages, log-out, admin, help, Your data, feeds, JSON,
  app files). `LEGAL_ACCEPTANCE_REQUIRED = False` in the test settings (`test_legal_versions` turns it on).
- **Public pages stay honest:** the home page's stats are real published-catalogue counts (`pages.views._catalogue_counts`, cached an hour); no invented numbers, testimonials or features. Every footer link must resolve (`test_site_pages` walks them). `pages:contact` emails `LEGAL_CONTACT_EMAIL` with Reply-To the sender (honeypot field, 3 per session per hour, disabled while the address is a placeholder); `pages:help` explains the lifecycle.
- **Notifications:** `apps.notifications.services.notify(user, kind, title, message, url, obj)` creates a `Notification` and emails it unless `user.settings.email_notifications` is off or the address is a placeholder (mail errors are logged, never raised); `notify_staff(...)` reaches everyone with `can_access_staff`. Kinds (seeded by notifications 0002): `submission_reviewed` (from `Approvable.approve/reject/request_changes` → `_send_approval_notification`, to the submitter/creator, gated by `ApprovalSettings.notify_on_approval/notify_on_rejection`), `submission_received` (staff, from `Approvable.submit_for_review`, gated by `notify_on_submission`; the activity forms now call `submit_for_review` instead of setting PENDING by hand), `role_request_decided` (accounts sends the `accounts.signals.role_request_decided` signal; `notifications/receivers.py` reacts, because accounts may not import notifications), `trip_access_granted` (`trips/signals.py`, on a new `TripGrant` not granted to oneself), `trip_invite_accepted` (`trips/people.accept`, to the inviter; created on first use, not seeded). The header bell loads `notifications:unread_count` (JSON) after the page, so pages pay no query; `/notifications/` lists them, opening one marks it read. Cross-app notification tests live in `apps/pages/tests/test_notifications_flow.py` (pages may import everything).
- **Visitor counts:** `visitor_count` on POI, City, Region (locations 0011) and Country = distinct members who ticked off a goal there or travelled (with an account) on a finished trip naming the city (`Trip.cities` / `Day.city`); regions/countries roll up their cities. `apps/bucketlists/visitors.recount()` recomputes everything (bucketlists may read trips; locations may not); `bucketlists/signals.py` queues one recount per transaction (on commit) when a completed goal or a finished trip changes, and `manage.py recount_visitors` runs nightly on production (James's crontab) because trips finish by date. Pages show "Members who've been" only when non-zero; top attractions / a city's places sort by it. The same pass keeps each member's **profile stats** (`accounts.Profile.countries_visited_count` / `trips_completed_count` / `bucket_list_completed_count`, shown on the profile page as Countries visited, Trips completed, Goals ticked off) by the same rule, creating a `Profile` for members who have something to show (`visitors._store_profiles`); before this fix nothing wrote them.
- **Place types:** a POI's type is a `locations.PlaceType` row managed in the admin (Locations → Place types; locations 0012 seeded the 14 old `POI_TYPES`), deliberately separate from activity/event categories (a type is what a place *is*). `POI.poi_type` is a FK on `PlaceType.code` stored in the original `poi_type` column (locations 0013), so set it with `poi_type_id="sports"`; the code is read-only once saved, a type in use can't be deleted (PROTECT), and unticking Active retires it from choices while its places keep it (`forms.active_place_types`, `PlaceType.choices()`). The CSV `type` column takes a code or a name; export writes the name.
- **Pictures first:** the location lists (countries, regions, cities, places) and the regions/cities/places on a detail page sort the ones with a picture first, then their usual order (`locations.views.pictures_first`). Dropdowns, forms and "recently added" stay as they were.
- **Maps:** every map is `templates/partials/_map.html` (`with data_url=… height=… route=True`) fed by a GeoJSON view of ours and drawn by `apps/core/static/core/map.js` through the adapter named by `settings.MAP_PROVIDER` (`osm` = Leaflet 1.9.4 + markercluster from cdnjs with SRI, OpenStreetMap tiles; `MAP_TILE_URL` / `MAP_ATTRIBUTION`; `GOOGLE_MAPS_API_KEY` reserved). Never call a provider's API from a page: a new provider is one more adapter (`create`/`group`/`addPoints`/`addLegs`/`addRoute`/`toggle`/`fit`) in `map.js`. Popups are built with DOM methods (names are user-submitted). OSM tiles need a Referer: the site sends `Referrer-Policy: same-origin`, so the tile layer sets `referrerPolicy: "strict-origin-when-cross-origin"` (origin only); without it OpenStreetMap shows "Access blocked" tiles. Places map: `locations:poi_map` / `poi_map_data` (published places, same Search/Country/Type filters as the list via `views._place_filters`; List/Map switch `locations/partials/_list_map_switch.html`). Trip map: `trips:trip_map` / `trip_map_data` (`Day.city` = where you spend the day (Munich on Oktoberfest day even when staying in Augsburg; where you sleep is the stay): days' cities in date order, consecutive repeats merged, numbered; transport legs with both `origin_city` and `destination_city` (trips 0018; choices = the trip's cities first, then all) drawn as lines styled by mode — flights arc, trains solid, road dashed — via the adapter's `addLegs`; without mapped legs the stops are joined by a plain line; leg cities and other `Trip.cities` are plain pins; never public; separate page so the detail query pin holds). A travel day (Augsburg → Munich → Manchester → Liverpool) is the main place you end up on the day plus one leg per hop. The trip map has switches (Cities / Places of interest / Travel legs): features carry `properties.layer`, the partial takes `extra_urls` (more GeoJSON merged in) and `controls` (id of the element with `<input data-layer=…>` switches), and the adapter draws each layer into its own `group()` that `toggle()` shows or hides. Places of interest come from `bucketlists:trip_map_places` (the viewer's *own* goals linked to the trip: goal POIs, activity venue, event venue; approved only), linked from the trip template with `{% url … as %}` so trips doesn't depend on bucketlists. **Stays** are `trips.Lodging` (a private booking, never a POI) with an optional `city` and `latitude`/`longitude` (trips 0019): `Lodging.locate()` fills the coordinates from the address via `apps/core/geocoding.geocode` (OpenStreetMap Nominatim, `GEOCODER_URL`, one request per save, identifying User-Agent; `GEOCODING_ENABLED`, off under `manage.py test`) — called by the stay forms (`LocatingStayMixin`: the stay page and the admin), never on a plain save, and not repeated for an address already tried (`geocoded_address`); hand-typed coordinates win. `manage.py geocode_stays [--trip] [--retry] [--fill-days]` backfills at one lookup a second. Saving a stay with a city through those forms also fills the city of the days it covers (check-in up to, not including, check-out) that have none (`Lodging.fill_day_cities`; never overwrites; adds the city to `Trip.cities`; the page that saved it says how many). A day's city is where you spend the day, so the stay fill is a best guess: a day trip is the destination on the day (set by hand) plus out-and-back legs from the stay's city; an overnight flight is a blank-city day plus the leg. The map's `stays` layer (house pin) shows name, city and dates only — never confirmation number, rate or notes — at the coordinates or else the city centre.
- **Editing places:** country, region, city and place (POI) pages end their right-hand column with the same Actions card (`locations/partials/_actions.html`: Edit, shown to staff or the item's submitter, and Back to the list) (`locations.views.can_edit`, passed to the detail templates as `can_edit`). Region/city/POI use ModelForms in `apps/locations/forms.py` (with `PictureFormMixin`; the city's region select follows its country) and the shared `locations/location_edit.html`; the country edit page is older and hand-written. Edits keep the slug and the approval status.
- **Reviews (`apps/reviews`):** members review published activities, events, cities and places (`apps/reviews/services.TARGETS`, kind → model / `Review` field / detail URL; a city is `Review.location`, a place `Review.poi` from reviews 0002), one per member per item, editable. Visible (`is_approved`) reviews set the item's stored `average_rating` / `review_count` (`services.recount`, from `reviews/signals.py`); the shared detail header and catalogue card show them as stars. The Reviews card is the shell partial `partials/_reviews.html` (`{% include … with kind="city" obj=city %}`, only on approved items), which loads `reviews:for_target` after the page, so catalogue apps never import reviews and pages pay no query. "Mark done" can share the goal's rating and notes as a review (`bucketlists` → `reviews` is allowed; never the reverse); `bucketlists/signals.py` marks a review "Been there" (`is_verified_visit`) when its author ticked that item off. Report (`reviews:report`) notifies staff (`review_reported`) and lists on the staff dashboard; 3 open reports hide a review until staff decide in the admin. The vendor and trip review types are unused (kept: `vendors` stays for a future vendor feature); R19 removed the site type and the response/helpful models (reviews 0005).
- **Rating a finished trip** (site roadmap R17; reviews 0004, notifications 0005): lives in **reviews**
  (`reviews` may use `trips`, never the reverse). `reviews/trip_ratings.py`: `targets(trip)` = the trip's
  published cities (trip, days, stays) and its activities' places; `ask(today)` sends one `trip_rating`
  notification to everyone with a grant on a trip that ended (up to 30 days ago), once ever
  (`reviews.TripRatingPrompt`); `save()` upserts reviews (`visit_date` = trip start; "Been there" only for
  people on `trip.travelers`). `reviews:trip_rate` (`/reviews/trip/<pk>/rate/`), linked from a finished trip's
  About this trip by URL name. The daily `send_trip_digests` fires `trips.signals.daily_run`, which reviews
  answers by calling `ask()` (no extra cron); `manage.py ask_trip_ratings` runs it by hand.
- **Catalogue notes on a trip** (catalogue-notes plan N2; trips 0046): `apps/trips/trip_notes.attach(trip, days)`
  (trip page and booklet, after the prefetch) gives each meal / trip activity / section linked to the catalogue its
  approved notes in one query — a section's activity first, then that activity's venue, then its place — as
  `item.trip_notes`, and `item.hidden_trip_notes` for those an editor hid on this trip (`trips.TripHiddenNote`, unique
  trip + note; `trips:trip_note_hide`, POST, `show=1` to bring one back). Shown under the item
  (`partials/_trip_notes.html`, "From <place> · checked Mon YYYY", Not for this trip for editors) and printed in the
  booklet (`pdf/_notes.html`, hidden ones skipped; the snapshot fixture has two notes and a hidden one). Never in the
  public view. **Warnings** (N3): `itinerary.note_warnings(days, tasks, today)` (no queries, after `trip_notes.attach`
  and `overview`) sets `item.closed_warning` ("Moab Diner is closed on Mondays", the item's day is one of its
  note's `closed_weekdays`) and `item.book_ahead` (per note with a lead time: book-by = the day minus it via
  `relativedelta`, `overdue`, `soon` within `BOOK_AHEAD_SOON_DAYS` = 30, `covered` when a to-do carries the note's
  hidden `BookingTask.FROM_NOTE` line), adds pressing ones to `day.attention` and returns the banner's lists ("N closed
  on their days", "N to book ahead"). "Add as a to-do" opens `trips:task_new?from_note=…&due=…` pre-filled; saving
  appends the hidden line (`task_edit`, `note_ids()`, hidden by `visible_notes`). The booklet prints both warnings.
- **Trip items linked to the catalogue** (site roadmap R18; trips 0044, locations 0014/0015, activities 0014):
  `Meal.poi` (a notable restaurant: most meals stay typed text), `Section.poi` / `Section.activity` and (catalogue-notes N4,
  trips 0047) `Section.event` / `TripActivity.event` (`forms.catalogue_events`: approved events overlapping the trip, its
  cities first; a section named like an activity on a day its event runs is offered the event), optional,
  SET_NULL; choices are the trip's cities (`forms.catalogue_places` — Food & drink first for meals — and
  `catalogue_activities`: published activities in those cities or country-wide in their countries), on the day
  page's meal formset and the section page. `apps/trips/catalogue_links.py`: on "On this day" an unlinked meal /
  section whose name matches exactly one of them (`match_keys`: capitals, spacing, punctuation, accents, German
  ö/ä/ü = oe/ae/ue) gets "Looks like …
  — Link / Not this one" (`trips:catalogue_link`, editors; a dismissal is a `TidyDismissal` keyed `catalogue:…`);
  never automatic. The trip page shows the links (`partials/_catalogue_link.html`, select_related in the
  prefetch, so the pin holds), the booklet plain text (`pdf/_catalogue.html`). `import_itinerary`'s dry run lists
  exact matches (`import_matches`), never links. **Counts:** `POI.trip_count` / `Activity.trip_count` /
  `Event.trip_count` (events 0008) = distinct live trips using it (a trip linked to an event also counts for the event's
  activity and venue) (`apps/trips/catalogue_counts.recount()`, run by the nightly `recount_visitors`); pages show
  "On trips" only via `shown_trip_count` (≥ `locations.models.TRIP_COUNT_MIN` = 2), never which trips. The
  `food` place type (Food & drink) was seeded by locations 0015.
- **Catalogue search** (site roadmap R20; core 0002 enables `pg_trgm` + `unaccent`, trusted extensions the
  DB owner may create; `django.contrib.postgres` installed): `pages:search` (`/search/`, everyone, 120 GETs a
  minute per IP) over `apps/pages/search.py` (in `pages` because it reads every catalogue app). `ranked(qs, q)`:
  full-text `SearchVector` per model (`FIELDS`: A name, B where, C category/type, D description; config
  `english`, every column through `unaccent`, the query through `strip_accents`) + `TrigramWordSimilarity` on
  the name (≥ 0.45, ≥ 0.7 under 5 letters) + a bonus for an exact (2.0) or leading (0.6) name, plus a substring
  match from 3 letters. Published only: approved countries/regions/cities/places, `Activity.get_public_activities`,
  `Event.objects.visible_to(user)` upcoming unless `past`. Kinds `KINDS` (area = countries + regions, city,
  place, activity, event); `Filters` (kind, country slug, month — event start / activity `usual_months` —,
  category, past; month/category leave activities and events). `grouped()` = up to 8 per kind, one query per
  model, so the page is a fixed 8 queries; `?kind=` paginates one kind. The box is the shell partial
  `partials/_search_box.html` in both headers (`url … as`). Results reuse `_catalogue_card` / `_event_card`.
- **What's on** (site roadmap R21; no migrations): `apps/events/whats_on.py`. **Calendar** `events:calendar`
  (`/events/calendar/<y>/<m>/`; `events:calendar_today` redirects to the reader's month): events the reader may
  see (`visible_to`), country/category filters, `month_events` (one query; an event's dates are local, so a month
  is a date range — only "today" depends on the reader) and `month_grid` (Monday first, an event on every day it
  runs, `DAY_CAP` 3 then "+N more" → the day list, which is the whole view below `sm`). **What's on / Things to do**
  on country, region, city and place pages: the shell partial `partials/_whats_on.html` (`url … as`) loads
  `events:whats_on` (`/events/whats-on/<country|region|city|place>/<slug>/`, 3 queries) after the page, because
  `locations` may not import `events`/`activities`; `events_for` = upcoming visible events in the place (venue:
  `poi`), a city adding others within `NEARBY_KM` (50; bounding box in SQL on the event's / venue's / city's
  coordinates, haversine in Python, `distance_km` shown as "Nearby"); `things_to_do` = public activities there
  (venue for a place), most popular first; the card hides itself when both are empty. **Add to my calendar**
  `events:event_ics` (`/events/<slug>/calendar.ics`, anyone who may see the event, else 404): timed → `TZID` of
  `Event.timezone` (+1 h without an end), else all day with an exclusive end. `apps/core/ical.py` (`calendar`,
  `vevent`, `DOMAIN`) is shared with the trip feed (R4; its output unchanged).
- **SEO basics** (site roadmap R22; no migrations): **place pages are public** — country / region / city / place
  lists, details and the places map need no login (add/edit still do); `locations.views.visible(qs, user)`: staff
  everything, members approved + their own submissions, visitors approved only (others 404); the lists' Status
  filter is staff-only (`_status_filter`). `/robots.txt` (`apps/pages/sitemaps.robots_txt`; `DISALLOW` = trips,
  public trip links, accounts, staff, admin, approval, notifications, bucket lists, search, What's on fragments,
  report, reviews; staging disallows all) and `/sitemap.xml` (`django.contrib.sitemaps`, `SITEMAPS`; on
  `SITE_URL`'s host, never the request's: public pages, everyone-guides, approved places, public activities,
  approved events from a year ago on). Every page: `partials/_seo.html` (in both bases' `{% block seo %}`) writes
  description, canonical (`CANONICAL_URL` = `SITE_URL` + path, no query), Open Graph + Twitter tags (default
  picture `DEFAULT_SHARE_IMAGE`, from `site_branding`) from the view's `seo` (`apps.core.seo.meta`); detail views
  pass `event_meta` / `activity_meta` / `place_meta` (`<app>/seo.py`), which carry schema.org JSON-LD (`Event` with
  local times + offset, `TouristTrip`, `TouristAttraction` / `City` / `AdministrativeArea` / `Country`) written by
  the `|jsonld` filter (`core/templatetags/seo_tags.py`, escapes `<` `>` `&`). `noindex` meta on search, public
  bucket lists and shared trips.
- **Profile "Recent activity"** (`apps/pages/activity_feed.py`, `pages:profile_activity` at
  `/people/<username>/activity/`, loaded after the profile page by the shell partial
  `partials/_profile_activity.html`, since `accounts` may not import what it reads): newest first, up to 10 —
  goals ticked off and added, badges earned, approved reviews, published activities / events / places the member
  added; the member also sees private goals and finished trips ("Only you"). Others see public items only; a
  private profile (or one waiting to be deleted) is the owner's only (404). Three or more of one kind on one day
  fold into one line ("Added 6 places: …", `_fold`).
- **Badges:** `apps/bucketlists/badges.py` defines them (code, title, icon, a counter and a target: goals added, ticked off, countries, events, trips, photos). `award_badges(user)` runs after every goal save (signal) and photo upload, records each new badge once as a `BucketListMilestone` (unique user + `code`, bucketlists 0006) and sends a `badge_earned` notification. `progress(user)` feeds the strip (`bucketlists/partials/_badges.html`) on the dashboard and My adventures; the public bucket list shows earned ones only. `manage.py award_badges` backfills silently (`--notify` to announce).
- **Recommendations:** `apps/recommendations/services.for_user(Goals)` scores public activities and upcoming events (new date for an undated goal > same category > same country > popular; one card per activity); `pages.views._goals` builds `Goals` from the user's bucket list because `recommendations` may not import `bucketlists`. The app has no models (R19 removed the unused ones, recommendations 0002).
- **Goal photos and My albums** (`apps/bucketlists/photos.py`): a goal has photos at any stage (`bucketlists:item_photos`, linked from its card and edit page; owner only; the dashboard and public cards show the first via `views._attach_first_photos`). A personal album is a `media_app.MediaAlbum` with no trip (`trip__isnull=True`; trip albums are `Trip.album`): `bucketlists:albums` (sidebar under Done, and My adventures), new/edit/delete, pick from your own goal and trip photos (`album_pick`), or upload straight in (that Media is attached to the album and deleted with it; borrowed photos stay on their goal or trip). `MediaAlbum.add()` / `items()` / `ensure_cover()` keep order and cover for both kinds. Albums are private, or public on the owner's public bucket list when their profile is public.
- **My adventures** (`bucketlists:adventures`, sidebar stage 5): completed goals by year with photos (uploaded on "mark done", up to 10, stored as `Media` attached to the item via `BucketListItem.add_photos` / `.photos()`), plus finished trips not tied to a goal. **Sharing a trip:** editors use Share / Stop sharing on the trip page (`trips:trip_share` / `trip_unshare` → `Trip.enable_public` / `revoke_public`).
- **Legal pages:** `pages:terms`, `pages:privacy`, `pages:safety` (templates in `apps/pages/templates/pages/legal/`, linked from `partials/_footer.html`). Company details come from `settings.LEGAL` (`LEGAL_*` in `.env`); while any is still a `[placeholder]` the pages show a draft banner. The wording is a starting template: when the site starts collecting new kinds of personal data, cookies or third-party services, update `privacy.html` to match, and have the text reviewed before public launch.

### Trips (`apps/trips`, merged from the itinerary project)

The itinerary project's `trips` app replaced ours in Phase 1. Its own CLAUDE.md
(`~/projects/itinerary/code/CLAUDE.md`) is the long-form reference; read the relevant section
there before changing the docx importers, section payloads, formsets or the dashboard. (That
project also kept its apps under `apps/`, so its paths line up with ours again.) The rules
that matter most:

- **Models:** `Traveler` (roster person, optional `user` link), `Trip`, `Day`, `Section`
  (`content` is JSONB; per-type shapes in the `apps/trips/models.py` docstring), `Meal`, `Lodging`,
  `TransportLeg`, `Confirmation`, `Contact`, `BookingTask`, `TripGrant`, generic `Comment`,
  `RewardsMembership`.
- **Access is per trip.** A `trips.TripGrant` row (one per trip and user) carries the person's
  `role` on that trip: `TripRole` viewer < commentor < editor; `role_capabilities()` is the rule.
  No grant, no access. **Creating a trip** is open to every active (email-verified) account unless
  staff ticked `User.trip_creation_blocked` (site roadmap R14; `can_create_trip`); `accounts.UserRole`'s
  `creator` is no longer checked (the staff trips dashboard still counts it). Creating a trip gives its
  creator an editor grant. Delete needs an editor grant *and* `created_by`; `restore` and `manage` (grant editing in the admin) are staff-only.
  Editors also have `invite` (site roadmap R1): the **People** page `trips:trip_people` (`/trips/<pk>/people/`,
  `apps/trips/people_views.py`, rules in `apps/trips/people.py`; linked beside Map · Budget · Photos and from
  Settings) lists everyone with a grant to anyone who can see the trip; editors invite (email + role),
  change roles and remove, never above their own role and never the creator (`people.can_set` /
  `can_remove`); anyone but the creator may leave. Inviting an address with an active account grants at
  once (`people.give_at_least`: creates or raises, never lowers; the usual `trip_access_granted`
  notification); otherwise a `TripInvite` (trips 0034: token, 14-day `expires_at`, one open per trip +
  email — partial unique `tripinvite_one_open`; Resend renews the token, Cancel sets `revoked_at`; 20
  sent per trip per 24 h) is emailed (`trips/emails/invite.txt`). `trips:invite_accept`
  (`/trips/invite/<token>/`, single use, any account may accept): signed out → login / register with
  `?next=` back (accounts' `register` keeps a safe `next` through the verification link and pre-fills
  `?email=`); signed in → **Join trip** (optionally adds their `Traveler` to `trip.travelers`), the grant
  is made quietly (`grant._quiet`) and the inviter gets `trip_invite_accepted`. The confirmation
  message is the same whether or not the address has an account. (The itinerary
  project had an app-wide role ladder; trips migration `0014` moved it onto the grants.) Views go through `Trip.objects.visible_to(user)` / `Trip.can(user, action)`
  / `Trip.capabilities_for(user)`: **404** with no grant, **403** when the trip is readable but
  the action is refused. `Trip.status`, `Trip.travelers` and booking-task names are never access
  checks. Staff/superusers get everything without grants. Trips are soft-deleted (`deleted_at`);
  `visible_to` hides deleted trips from everyone, recovery is an admin action.
- **Every account is a traveler.** `apps/trips/signals.py` links or creates a `Traveler` on every
  user save (unique exact-name match only). Travel-profile data (passport, loyalty numbers) is on
  `Traveler` and visible only to that person and staff (`Traveler.is_private_to`).
- **Public view:** `/public/<uuid:token>/` (`public_trip`) renders `apps/trips/public.py`'s
  allowlisted dict, never a `Trip`; sections, themes, lodging, transport, confirmations and
  travellers are omitted on purpose. `manage.py audit_public_leak` checks the real data (exit 1
  on a certain leak).
- **Rewards programs** (site roadmap R11; trips 0041/0042, rewards 0003): `trips.RewardsMembership` (per
  `Traveler`, private like the rest of the travel profile) is the only membership model; `catalogue_program`
  links an optional `rewards.RewardsProgram` (the form fills the name and kind from it; `?program=<id>` on
  `trips:traveler_profile` pre-picks it). trips 0042 copied `rewards.UserRewardsMembership` rows onto each
  account's traveller (matching an existing row by link, name, "company name" or a typed name containing the
  program's) and declares `run_before` rewards 0003 (which dropped that model), so `rewards`' history never
  depends on `trips`. `rewards` is now the catalogue only (browse / detail); its old membership URLs
  redirect to the travel profile by URL name.
- **Status badge and completion:** `Trip.status` is a hand-set planning stage (Starting → Fleshing out → Confirming → Ready to go). The badge (`trips/partials/_status_badge.html`, `Trip.badge`) shows that stage, or **Completed** once `end_date` has passed (`Trip.is_completed`, derived from the dates, never stored); the trip list puts finished trips under "Past trips". Saving a trip as Ready to go with open booking tasks shows a warning (as the admin already did). A finished trip's page shows the shell partial `partials/_trip_bucket_prompt.html` (`url … as`, no query, so the query pin holds), which posts to `bucketlists:trip_done`: the user's goal linked to the trip goes to its "mark done" page, or one is created for an unlinked trip. Tests that use the fixed 2026 fixture dates pin today with `mock.patch("apps.trips.models.django_timezone.localdate", new=…)`.
- **Places:** `Trip.cities` (M2M to catalogue cities) and `Day.city`. Every city field on the trips forms (a day's, a stay's, a leg's from / to, the route's stops, Settings' Cities) is a **type-to-search box** (day-first plan P1): `apps.locations.widgets.CitySearchInput` / `CitySearchMultiple` (Alpine, `locations/city_search.js`) over `locations:city_search` (`/locations/cities/search.json?q=&country=`, `apps/locations/city_search.py`: unaccent + trigram on the name + exact/leading bonus, like `pages.search`, which locations may not import; approved cities plus the member's own pending ones; up to 10; 120 GETs a minute), keeping the id in a hidden input that carries `data-tz` and fires `change` (the leg page's zone fill). Before typing it offers the **This trip** group as chips; without JavaScript it is hidden (`x-cloak`) and the old grouped select (**This trip**, then **Everywhere else**; `forms._leg_city_fields` / `_trip_city_choices`, built once per page and cached on the trip) in a `<noscript>` submits instead — the hidden input is named only by Alpine (`x-bind:name`), so the two never both submit. **Add “X” as a new city** in the box (or `locations:city_new`, `/locations/cities/new/`, the no-JS page; `NewCityForm`: name, country, optional region; 20 an hour) makes a **pending** city (coordinates from `core.geocoding`, else the country's centre; `submit_for_review`), returning one the member can already see instead of a duplicate. The trips forms accept approved cities, the trip's own and the signed-in member's pending ones (`forms._city_choices(trip)`, via `apps.core.current`). **Cities maintain themselves:** `apps/trips/trip_cities.sync(trip)` adds every city a day, stay, leg end, the catalogue place / event of a trip activity, meal or section, or an idea's place (P6) uses; never removes. Called by `SyncsTripCitiesMixin` (day, stay, leg, section, trip activity forms), `day_edit` (meals), Settings, the leg quick add, `travel_tables.apply`, `Lodging.fill_day_cities` and the route builder. Settings' Cities are chips; `TripForm.clean_cities` refuses to remove one something uses (`trip_cities.used_by`: "Munich is used by Day 3, Hotel Laimer Hof"). "Plan a trip" / adding a goal brings its city through the idea it becomes (P6). Recommendations count the countries of the user's upcoming trips. Cities are never in the public view. The free-text `destination` stays for display and the public title.
- **Route builder and strip** (day-first plan P1; `apps/trips/route.py`): `trips:trip_route` (`/trips/<pk>/route/`, editors; linked from the strip, Settings' Days and, on a trip with no day cities, "Set the route" on the trip page) — `RouteFormSet` rows of city + nights (three blank rows more after each Preview), starting from `route.initial_stops(days)`. `route.plan` lays them over the trip's dates (the travel day belongs to the next city, the last city also has the departure day; a longer route is cut at the end unless **Extend** moves `end_date`, a shorter one leaves the last days blank) and lists days to fill (missing `Day` rows are made), days kept because they have another city (unless **Replace**), legs and stays; Preview saves nothing. `route.apply` (one transaction, `changes.batch("Route set: …")`): days' cities, a planned leg per travel day (`mode` "other", cities, names and zones from the cities; skipped when that day already has a leg between them) and a placeholder stay per city ("Stay in Munich", no address, so it shows in Not booked yet; skipped when a stay overlaps those nights), then `trip_cities.sync`. The **route strip** above the Needs attention banner, "Munich (3) → Salzburg (2)", is `route.runs(days)` (consecutive days with one city, blank days skipped; no queries), each linking to `#day-N`, with Edit route for editors. Not in the booklet.
- **Budget in one currency** (site roadmap R10; core 0001, trips 0040): `core.ExchangeRate` (date, currency,
  `per_euro`) holds the ECB's daily reference rates, fetched by `manage.py fetch_rates [--history 90d|all]`
  (production cron after ~16:00 CET; outbound HTTPS to www.ecb.europa.eu). `apps.core.rates.Rates(currencies,
  dates, overrides)` loads what a page needs in one query and `convert()` returns a `Conversion` (amount,
  rate, source ECB / trip / same, rate date, `latest` when a dated rate wasn't there) or None for an unknown
  currency (listed, never guessed). `trips.TripRate` (1 from = rate to) is the editor's override, both ways,
  edited on the Budget page under **Your own rates** (`trips:trip_rates`, POST, editors; everyone sees them; moved from Edit trip in E3). Budget page: `?in=XXX` (default the reader's
  `settings.preferred_currency`) converts each cost at its `spent_on` rate (`budget.in_one_currency`), shows
  "≈" totals and "Rates used"; `?settle=1` settles in it, otherwise settle-up stays per currency. About this trip:
  `budget.estimate` = confirmation `cost` + activity `est_cost` in the reader's currency (two queries only when
  something is foreign). `apps/core/utils/currency.py` (currency codes, `format_currency`, the catalogue's
  `|convert_curr` filter) converts with the same stored rates since R19 (`convert_currency(amount, from, to, on=None)`
  → `Rates`; unknown currency → None); the site makes no live exchange-rate calls and `requests` is gone from
  `requirements.txt`.
- **Currency choices** (edit-by-day plan E4; trips 0045): `Trip.home_currency` (Settings → The trip, `TripForm`'s
  select of the current one, the creator's, `HOME_CURRENCY_CHOICES` and Other…, no queries; `Trip.save()` fills a blank
  one from the creator's `AccountSettings.preferred_currency`, else USD; 0045 set existing trips from their creators).
  Every currency field on the trip's forms (stay, leg — also `LegEditForm` —, trip activity, task option, confirmation,
  cost, the Budget page's own rates) is `apps/trips/currencies.setup()`: a `CurrencyField` (three letters, uppercased;
  blank only where the model allows) with `apps.core.widgets.CurrencySelect` (the trip's home currency, then the local
  ones from `Country.currency_code` of the item's places — table in `currencies.py`'s docstring — then Other…, a typed
  box that Alpine hides until picked and that wins whenever it has text, so it works without JavaScript; a stored code
  outside the list is added and shown, never changed). Country codes and the trip's cities are cached on the trip
  object (`_currency_cache`), so formsets don't query per row. A new item starts on its one local currency, else home
  (`currencies.default_for`; also the leg quick add). The admin's own forms are unchanged.
- **Budget:** `TripExpense` (who paid, `shared_with` travellers; empty = everyone on the trip). `trips:trip_budget` (`/trips/<pk>/budget/`, linked from the trip header) shows totals per currency (no conversion), each traveller's paid/share/balance and a settle-up (`apps/trips/budget.py`: cents, payer absorbs odd cents, largest debtor pays largest creditor). Anyone who can see the trip sees it; editors add/edit/remove costs. Never in the public view; a separate page so the detail page's query count is unaffected.
- **Change digest** (site roadmap R7, trips 0037, notifications 0003): `apps/trips/changes.py` records a
  `TripChange` (trip, actor, kind added/changed/removed, item, `summary`, `digest_sent_at`) from
  `pre_save`/`post_save`/`post_delete` on legs, stays, activities, meals, sections, days and
  confirmations (only the fields in `TRACKED` that really changed, with readable before → after; leg times
  through `departure_local_str`), plus confirmation links and ticket files. The actor is the request's user
  via `apps.core.current` (set by `apps.core.middleware.CurrentUserMiddleware`; None in scripts). Removals
  only for the object deleted on purpose (the signal's `origin`), so cascades (a day's meals, a whole trip)
  aren't listed. `changes.batch(summary, trip=None)` writes one "… (N changes)" line per trip: wraps
  `import_itinerary`, `travel_tables.apply`, `tidying.apply`. A leg's time/date change departing within
  `URGENT_DAYS` (7) notifies everyone at once (on commit). `manage.py send_trip_digests [--dry-run]` (daily
  cron on production) sends each person with a grant and `TripGrant.notify_changes` one `trip_changed`
  notification per trip, without their own changes, then marks the changes sent. ⋯ → Stop emails / Email
  me about changes (`trips:trip_notify`); the trip page gets the flag from the same query as its
  capabilities (`Trip.capabilities_and_grant`), so the pin holds at 28.
- **History and undo** (site roadmap R8, trips 0038): `TripChange.day` (for the day filter; `changes.day_id_of`)
  and `TripChange.before` (JSON): `{"before", "after"}` field values for a change, or for a removal a
  `changes.snapshot` taken in `pre_delete` (serialized row + M2M, confirmation links, contact/info links,
  booking tasks). `trips:trip_history` (`history_views.py`, anyone who can see the trip; Day / Person /
  Kind filters, 50 a page, lines link to `trip_detail#<anchor>`, linked beside People) and
  `trips:change_undo` (editors): `changes.undo` only for the item's newest change (`latest_change_ids`) and
  only if its fields still hold the "after" values, saved normally so it is recorded; `changes.restore`
  brings back a removed leg, stay, activity, meal or section (`RESTORABLE`) with its original pk and links
  under `changes.quiet()`, refuses when its day or trip has gone, and records "Restored …". Days,
  confirmations (files are deleted) and trips aren't restorable. `send_trip_digests` also prunes sent
  changes older than 180 days.
- **Checklists** (site roadmap R9, trips 0039): `Checklist` (trip, title, kind packing / documents / before /
  other, order), `ChecklistItem` (text, `per_person`, order; a shared item's `done_at` / `done_by`) and
  `ChecklistTick` (per-person: item + traveller, unique). `apps/trips/checklists.py`: `attach` (from the trip
  page's `checklists__items__ticks` + `travelers` prefetch, no query: `item.boxes`, `is_done`, list
  `done`/`total`), `attention` (empty boxes on documents lists from 14 days before the start to the end →
  the Needs attention banner's "N documents not ticked"), `trips:checklist_tick` (`comment`; form POST, 204 for Alpine's
  background `X-Requested-With: fetch`), and editors' `checklist_new` / `_edit` (items formset) / `_delete` /
  `_from_template`, reached from Settings' Checklists section. Per-person items use `trip.travelers`
  (none → acts shared). Templates: `apps/trips/checklist_templates/*.md` (header `title` / `kind` /
  `summary`, then `- item` lines, `- [each] …` per person; parsed strictly by the tests). Shown in
  Reference (`partials/_checklist.html`) and the booklet's Reference. Not in the change history. Never public.
- **Offline trip page** (site roadmap R6): a service worker `apps/core/static/core/sw.js`, served at
  `/sw.js` by `apps.core.pwa.service_worker` (no-cache) and registered only by the trip page
  (`trips/partials/_offline.html`) with **scope `/trips/`** and `?u=<apps.core.pwa.offline_cache_key(user)>`
  (an HMAC, per person; `&debug=1` in DEBUG so unhashed static isn't cache-first). It saves only
  `/trips/<pk>/`, `/trips/<pk>/booklet.pdf` and `/trips/<pk>/files/<id>/` (network first, 4 s, then the
  saved copy, whose `data-sbl-offline hidden` banner it switches on) plus `/static/` and the CDN files
  (cache first); never edit pages or anything with a query string. A new key deletes other
  `sbl-offline-*` caches. ⋯ → **Save for offline** (Alpine `offlineSave`) stores the page, booklet,
  the page's `/files/` links and its CSS/JS. `templates/partials/_offline_cache.html` (both bases: the
  manifest link + theme colour) deletes the caches and unregisters the worker on every signed-out page
  (only when `request` is in the context, so the context-less 500 page doesn't) and before the logout
  form submits. `/manifest.webmanifest` (`apps.core.pwa.manifest`): start `/trips/`, branding icons.
  Manual check list in `docs/plans/site-roadmap.md` (R6).
- **Calendar feed** (site roadmap R4, trips 0035): **Add to calendar** in the trip page's ⋯ menu (now shown
  to everyone who can see the trip) → `trips:trip_calendar` (`/trips/<pk>/calendar/`, `calendar_views.py`):
  the viewer's own `TripCalendarToken` (made on first visit; one live per trip + user, partial unique
  `tripcalendartoken_one_live`; Reset sets `revoked_at` and makes a new one), subscribe how-tos, "Only the
  things I'm on" (`?mine=1`). The feed `trips:trip_calendar_feed` (`/trips/calendar/<token>.ics`, no login)
  re-checks on every fetch that the token is live, the owner active and `trip.can(owner, "view")` (404
  otherwise) and is built by `apps/trips/calendar.py` (`icalendar`): timed legs in UTC, timed activities and
  reserved meals as **floating** local times (+1 h without an end), planned legs and untimed activities
  all-day, stays check-in → check-out; descriptions carry operator, service number and **confirmation
  numbers** (James's decision) and a link to `trip_detail#<anchor>`; stable UIDs `leg-<pk>@sharebucketlist.com`.
  `mine`: activity travellers, else (an item on a split group's track, day-first P5) its option's travellers, else the
  day's (`options.on_it`); legs/meals by their track, else the day's; blank = everyone; stays always unless on another
  person's track. 13 queries per fetch with the undecided groups and their options (P4) and who takes each split option
  (P5; `test_calendar.FeedTests.test_fixed_query_count`). Never public.
- **Photos:** each trip has one shared album (`Trip.album`, a `media_app.MediaAlbum`, made on first upload by `Trip.add_photos`; trips 0017; the first photo is the cover). `trips:trip_photos` (`/trips/<pk>/photos/`, linked from the trip header): anyone who can see the trip sees them, `comment` capability adds, the uploader or an editor removes (`Trip.remove_photo` moves the cover on), editors pick the cover. Photos are `Media` attached to the trip, privacy private; never in the public view; a separate page so the detail query count holds. My adventures shows the album cover. The multi-photo upload field (`MultipleImageField`, `MAX_PHOTOS`) lives in `apps.media_app.forms`.
- **Leg times** are stored UTC with an IANA zone per endpoint; render with the model's
  `*_local_*` helpers or the `trip_time` filters (`|at_zone:`…), never `|date` after them.
- **Planned legs:** a leg has a `date` and its times are optional (trips 0020): with no times it is
  *planned* (`TransportLeg.is_planned`), shown as "planned · no times yet" and drawn fainter on the map;
  times, once booked, set `date` from the local departure (`save()`). Forms need both times or neither,
  and a date when there are none. Legs order by date, then time. **Logistics tables → legs** (`apps/trips/travel_tables.py`, trip-items plan Phase C): one
  plan, three callers — "Turn into legs" on a table (`trips:section_to_legs`), the trip-wide review
  (`trips:trip_travel_review`, `/trips/<pk>/travel-tables/`, linked from an editors' banner on the trip
  page while any table still has an arrow row; `travel_tables.has_pending` reads the prefetched
  sections, no query) and `manage.py convert_travel_tables --trip <pk> [--apply]` (dry run by
  default). `apps/trips/logistics.py` (pure) reads each travel row: mode from its words, operator
  from a Train/Mode/Operator column, `duration` from a Time column or the first "~35 min" in the
  row, a leading verb dropped ("Depart ABQ → SLC" is ABQ → SLC), and a `strength` — `arrow` rows are
  ticked, `possible` ones (found only by the word "to", or "Via A → B") start unticked, so day
  schedules ("Continue to Angel Fire") are left alone. A row that is already a leg on that day (same
  wording, same city pair, or each end naming the other's: "Depart ABQ" / "ABQ") **links**: the leg
  is placed in the section and only gains an empty rough time / operator / notes; otherwise a
  planned leg is created (`est_duration`, `order` = row order, cities matched by name, trip's
  first). Each table with a ticked row becomes a `travel` section: converted rows and "Total…" rows
  go (their non-time text joins the last leg's notes, `logistics.total_notes`), other rows stay as
  reference rows. Nothing is saved before confirming; times are never guessed (see `docx_europe`'s
  docstring). **New itineraries start as legs** (Phase D): `import_itinerary --apply` runs
  `travel_tables.convert_automatically` on the new trip in the same transaction (arrow rows only;
  a row naming one of the document's own flights links to it), `--keep-tables` skips it, and the dry
  run lists the hops. The parsers stay pure and still emit `logistics_table` sections (the day page no longer offers
  the type, E6; a table's page offers "Turn into legs" and "Make it travel notes"). The section
  editor lists a travel section's legs ("Legs shown here", Edit links that come back to it) with the
  quick add (`leg_quick_add` honours `next`), and a logistics table with arrow rows links to "Turn
  into legs".
- **One leg, two views (trip-items plan, Phase A):** a leg is shown once in the trip-wide
  **Getting around** list and once on its day, both through `trips/partials/_leg_row.html`
  (mode, A → B, operator, local times or "planned · ~45 min", stage badge, editors' Edit link).
  On its day it sits in the `travel` section it's placed in (`TransportLeg.section`, a `travel`
  section of the day whose date is the leg's `date`: checked in `clean()`, cleared by `save()` if
  the date or section type no longer fits, so the leg falls back instead of vanishing), else in the
  day's automatic "Getting around" block; legs on a date that is no day of the trip are flagged for
  editors. `itinerary.place_legs` does the grouping in Python from the existing `transport` /
  `days__sections` prefetch (`section.placed_legs`, `day.auto_legs`, `day.travel_total` "2 legs ·
  ~3 h 15 min") — no new queries. `stage` is derived ("planned" without times, "scheduled" with,
  "booked" once a confirmation covers it); `est_duration` holds the rough time (`logistics.rough_duration`
  parses "~45 min", "2.5 hrs", "1:15"); `order` sequences same-day legs without times. A `travel`
  section's payload is `{"intro"?, "columns"?, "rows"?}` — rows are reference rows only, never hops.
  **Zones from cities** (E5): on save a blank origin / destination zone takes its city's `City.timezone`, and a
  blank origin / destination text its city's name (`TransportLegForm.fill_from_cities`, before the local times are
  converted; a zone typed in is kept); the leg page's script fills a blank zone as a city is picked (`data-tz`);
  `leg_quick_add` sets the zones from the cities it matched.
  Editing: `trips:leg_edit` (grouped Route / Schedule / Details / Placement / Return, `next`
  checked with `url_has_allowed_host_and_scheme`), `trips:leg_delete`, `trips:leg_quick_add` (a
  planned leg typed like a table row on a day, cities matched by name), `trips:day_add_travel`.
  Bookings lists every leg read-only under Getting around & stays (E3 on Edit trip; moved in P7).
- **Round trips:** a leg's own page (`LegEditForm`, extending `TransportLegForm`) has "Also add the return trip"
  plus the return's local departure/arrival; saving creates a second, independent leg with the ends,
  cities and zones swapped (return departs in the destination's zone, arrives in the origin's) and
  mode/operator/currency copied, but not service number, confirmations, cost or notes. The fields are
  added in `__init__` (`LocalLegTimeMixin` rebuilds `declared_fields`). The admin stays one-way.
- **Confirmations attach like comments** (trips 0026–0028): a `Confirmation` holds the booking's own
  details (number, provider, optional `label`, `url` manage-booking link, `booked_on`, `cost` + `currency`
  for the whole booking, notes, `travelers` — blank = everyone); what it covers is `ConfirmationLink`
  rows, each a generic link (content type + id) to one item of the same trip: a leg, a stay, an activity, a day's
  section or a meal (`models.CONFIRMABLE`; `link()` checks the trip, once per
  item; each item model's `confirmation_links` GenericRelation deletes its links with it). One record can
  be linked many times (GCH7JS on four legs). Adding happens **on the item**, on edit pages only:
  `trips:item_confirmations` (`/trips/<pk>/confirmations/<kind>/<id>/`, editors; the leg edit page shows
  the same block, `partials/_item_confirmations.html`): type a number (`Confirmation.attach_number`: a
  number the trip already has, trimmed and case-insensitive, links to that record; else creates it —
  also what `import_itinerary` does), pick an existing one, or remove it from the item (never deletes
  it). `confirmation_edit` edits a confirmation's own details and lists what it covers;
  `confirmation_new` is for loose ones (insurance). The trip page prefetches the links (with content
  type) and `views._attach_confirmations` resolves them against the legs, stays, sections and meals it
  already has: chips on each item, `leg.stage` "booked", and Quick reference → Confirmations generated
  (`confirmation_groups`: Flights / Trains / Stays / Activities (sections) / Meals / Other by
  `Confirmation.kind`, each ordered by `first_date`). `audit_public_leak` takes numbers from
  `trip.confirmations`; confirmations are never public.
- **Tickets and documents** (site roadmap R5, trips 0036): `ConfirmationFile` on a confirmation, in
  `private_storage` at `trips/<trip>/<uuid>.<ext>` (never under `MEDIA_ROOT`; backed up with
  `private_uploads/`). `apps/trips/files.py` accepts by **contents** (PDF `%PDF-`; Pillow PNG/JPEG;
  HEIC/HEIF stored as JPEG), 10 MB a file, 200 MB a trip; `confirmation_file_add` / `_delete` for
  editors (on the confirmation page's Tickets & documents card and under each confirmation in an item's
  Confirmations block, `partials/_confirmation_files.html`), `confirmation_file` (download, `view`; inline
  under the original name, nosniff, `no-store`, CSP `sandbox`). Chips show "📎 n", Reference rows link
  the files, the booklet lists names only. A `post_delete` signal removes the stored file (also on a
  confirmation's cascade). Never public.
- **Activities on a day** (`TripActivity`, trips 0029; named so because the catalogue has `Activity`):
  `kind` (tour / timed entry / ticket or pass / table reservation / car hire / other), `title`,
  `provider`, local `start_time` / `end_time` (wall clock on the day, no zone), `poi` (a catalogue place
  in one of the trip's cities — `TripActivityForm` limits it) or `place_text`, `travelers` (blank =
  everyone), `est_cost` + `currency`, `notes`, `order`. Added and edited from the day page ("Activities",
  `trips:activity_new` / `activity_edit` / `activity_delete`); a new one lands on its own page so its
  confirmation can be added at once (it's a `CONFIRMABLE` kind, "activity"). Shown on its day (an
  "Activities" block, `#activity-<pk>`), in the PDF; never public. Booking
  tasks may point at one (`BookingTask.activity`; `bookingtask_one_item` allows at most one of leg / stay
  / activity), suggestions match an activity whose title the task names, and "Not booked yet" includes
  bookable kinds (not "other") with no confirmation and no task.
- **One page to read and edit; trip-wide pages are views; Settings holds trip-level things** (day-first plan
  P2–P7, replacing edit-by-day E3's "the view page is for reading"). On the trip page a click on an item opens it in
  the **item panel** (P2), each open day ends with **+ Add** (P3), "choose one" groups sit in their days (P4–P5) and
  ideas wait on the **Ideas shelf** (P6). Stays, legs, activities, meals, notes and to-dos are added there (or on the
  day page, `day_edit`, the no-JS fallback, whose Add to this day starts with the same one-line + Add, posting
  `next` back to itself — `quick_add` honours `next`, P7) and edited on their own pages, where their confirmations and
  contacts are added too. **Settings** (`trips:trip_settings`, `/trips/<pk>/settings/`, editors; `views.trip_settings`;
  the old `trip_edit` URL redirects; template `trip_form.html`, shared with New trip) has The trip (a save that moves
  the dates so the days don't fit goes to `trips:trip_days_fit`, `apps/trips/day_fit.py`: `plan` = dates without a day
  and days outside the dates with what's on them; `apply(trip, add, remove)` makes / deletes them (empty ones ticked,
  journeys and stays aren't tied to a day) and `renumber`s every day in date order, one history line), Days (`#days`),
  a pointer to Bookings, **Loose confirmations** (`#loose-confirmations`), Contacts & info and Checklists; the header
  button is **Settings** (`data-settings-link`). The **trip-wide views** are read-only and open items on the trip
  page: a link `trip_detail?item=<anchor>#<anchor>` opens the item's day (hash script) and the item itself in the panel
  (`panel.js` reads `?item=`): **Bookings** (`trips:trip_bookings`, `/trips/<pk>/bookings/`, anyone who can see the
  trip; the page context plus `views._edit_trip_stays_and_legs`: the confirmations (`partials/_confirmation_groups.html`,
  shared with Reference, `elsewhere=True`), Not booked yet (`partials/_not_booked.html`, shared too) and **Getting around
  & stays** (`#stays-legs`: every stay and leg in date order with its day and confirmation chips, strays flagged, the
  "Turn “A → B” table rows into journeys" link)); **To do** (choices, then Not booked yet, then the to-dos; to-dos keep
  their own pages); the map page's lists; the calendar feed's links. The header links Bookings · To do · Map · Budget ·
  Photos · People · History; the jump bar gains **Ideas** while the shelf has any. Budget keeps its own costs and rates.
  The booklet has no links.
- **Booking tasks point at their item** (trips 0025, Phase E): `BookingTask.leg` / `stay` (optional,
  SET_NULL, at most one — `bookingtask_one_item`; Phase F adds `booking`). `apps/trips/booking_tasks.py`
  works from the trip page's prefetches (no query): `attach` gives legs/stays `open_tasks` ("Still to
  book: …" on the leg row and stay card) and each task `item` / `item_day` ("For: … · Day 4"), and for
  editors a `suggestion` when an unlinked task's title names exactly one stay (by name) or one leg
  (first word of each end): "Looks like: … — Link / Not this one" (`trips:task_link`; a dismissal is a
  "Not about: <item>" line in the task's notes, hidden by `visible_notes`). `not_booked` is the derived
  "Not booked yet" list: flights, rental cars, trains with an operator or service number, and stays with
  no confirmation and no task. When a save gives a leg or stay its **first** confirmation
  (`trips:item_confirmations`) and it has open tasks, the user lands on `trips:task_offer`
  to tick them off — offered, never automatic. `BookingTaskForm(trip=…)` (the to-do page, E2) scopes its
  day / leg / stay / activity / confirmation pickers to the trip.
- **The detail page** holds a fixed query count (38 here — P6 the Ideas shelf and its votes (the page only; the day fragment stays at 36); P5 who takes each option of a split; P4 the "choose one" groups, their options and votes; N2 the catalogue notes of linked items, one query, none when nothing links to the catalogue; R5 added the confirmations' files, R9 checklists, their items and ticks, R10 the rates and the trip's own rates when a cost is in another currency; R11 removed the rewards context processor's query, R21 the time-zone middleware's own one — 2 of them from this site's
  middleware/context processors; one is the trip's cities; two are the confirmations' links and
  travellers; two are the days' activities and their travellers; two are item links and info notes;
  one is the tasks' options; three are the "choose one" groups, options and votes (P4: 35) — fixed per page, not per item); `test_detail.QueryCountTests` pins it (it warms the
  content-type cache first, so the count doesn't depend on test order).
- **The web trip page is laid out for the web** (trip-page UX plan, U2; the booklet does the printing,
  so add no print styling): a header (title, dates · nights · status; Settings and Download PDF;
  Bookings · To do · Map · Budget · Photos links; a ⋯ menu, Alpine, with Add to calendar, Tidy suggestions (editors), Share /
  the shared link / Stop sharing and Delete), the **Needs attention** banner (`#needs-attention`, only when
  something does: not booked, to do, decisions, documents not ticked, not on any day, tables to convert,
  each linking to its list), a sticky jump bar (Days · Reference), then:
  - **The days are the overview** (`docs/plans/trip-days-as-overview.md`; the web Overview table is gone,
    the booklet's "Days at a glance" page is unchanged). Each day's `<summary>` has line 1 (Day N · date ·
    city — theme) and line 2, `.day-glance` (`data-day-glance`), from `itinerary.overview` and
    `attach_stays`, each part only when it has something: 🛏 the stay (linked to `#stay-N`; "(check in)" on
    its first night, "(check out)" on a last morning with no stay that night), "✈ overnight" (a leg that
    day arrives a day later), travel (mode icons + "A → B" or the travel total), up to two highlights
    (activity titles only: the theme is already on line 1), and ⚠N (not-booked items and open tasks that
    day) linking to the banner. Links inside a `<summary>` follow without toggling it. Above the days:
    **About this trip** (`<details class="about-fold" id="about">`, closed unless the trip has no days;
    not touched by Expand all): travellers, cities, destination, goals, the bucket prompt, Rate the
    places, trip notes and the estimated cost (`#cost-estimate`, with its Budget link); then "Journeys
    not on any day" (`#stray-legs`) and "Stays outside the trip's days" in full, for everyone
    (`#not-on-any-day`). The hash script maps `#overview` (old bookmarks and emails) to `#days`.
  - **Days** (`#days`): each a `<details class="day-fold" id="day-N">`, open on arrival only for
    `itinerary.open_day` (today's during the trip, Day 1 before it, none after; `localdate()`); an
    inline script opens the `<details>` holding any `#target` (on load, on hashchange and on a click
    to the current hash) and drives Expand all / Collapse all (`data-days-toggle`). Inside a day (U3):
    the **stay line** (check-out first, then the stay's full card `partials/_stay_card.html`
    `#stay-N` on its check-in day, or "Sleeping: <stay>" linking to it on other nights), then the
    **timeline** (`itinerary.timeline`: legs by local departure — never the reader's zone —
    activities by `start_time`, meals by `Meal.reserved_time` (trips 0030), then **Any time**:
    untimed legs in `order`, then untimed activities), rows `_leg_row.html` with `compact=True`,
    `_activity_row.html`, `_meal_row.html` (`#leg-N`, `#activity-N`, `#meal-N`); then the
    **narrative** in section order (travel sections show only their intro and reference rows —
    their placed legs are in the timeline); then **Food ideas** (meals with no reservation time).
  - **Notes:** anyone with the `comment` capability can start a note on a day (**Add a note to this
    day**, at the end of the open day), on a section or on a task in Reference (**Add a note**), each
    shown only while it has none; once it has notes, its thread's **Add a comment** takes over.
    Posting or editing a comment returns to `trip_detail#comment-N` (one anchor — the comment sits
    inside its day, so the page opens it).
  - **Reference** (`#reference`): the home of confirmations (one row each, `#confirmation-N`, number
    in monospace, linking to its first item via `confirmation.anchor`), Still to book, Not booked
    yet and Contacts. Confirmation chips on items are links to their row.
- **The item panel** (day-first plan P2; mechanism: plain `fetch` in `apps/trips/static/trips/panel.js`, no htmx, so no
  new CDN file): on the trip page a click on an item (rows and cards carry `data-panel` = the edit URL for editors, else
  `trips:item_panel`; Edit / Edit this day links carry `data-panel-link`) opens its page in `#item-panel` (a side panel from
  `sm`, a full-screen sheet below). Any trips page renders without the site chrome with `?panel=1`: `base_trips.html`
  extends `trips/_panel_base.html` then (content + messages, `data-panel-title`). The panel opens `<edit url>?panel=1&next=
  <same>?panel=1`, so a save redirects back into the panel ("Saved", stays open); forms and `/trips/` links inside stay in
  it (a link to the trip page closes it; files, PDF, iCal and `_blank` links don't), a 404 (deleted) closes it, inline
  scripts are re-run (the leg page's zone fill is written to run once per page) and `locations/city_search.js` is loaded by
  the trip page for editors so the city box works inside. Tabs are built from `data-panel-tab` markers (`details` /
  `booking` / `people` / `contacts` / `comments`; an element may list several; a tab exists only when something is marked
  with it alone): `_form_fields.html` marks `travelers` as people; the leg, stay, activity and meal pages wrap to-dos and
  Confirmations as booking and Contacts & info as contacts; the section and day pages add their comments (`views._target_comments`)
  in panel mode only, and the day page in the panel is just its details and meals (no workshop). After a save the item's
  day, and any other day showing the item's anchor (a stay's nights), is swapped for `trips:day_fragment`
  (`/trips/<pk>/days/<day_pk>/fragment/`: `trips/partials/_day.html` alone, open, from `views._trip_page_context` — the
  page's context, shared with `item_panel`; `request.path` is set to the trip page so its links' `next` are right; pinned at
  the page's 32 queries, `test_detail.DayFragmentQueryTests`); an item gone from every day (a leg given another date)
  reloads the page at its anchor. `trips:item_panel` (`/trips/<pk>/panel/<kind>/<id>/`, kinds leg / stay / activity / meal
  / section / day, anyone who can see the trip): the item read-only through the page's own partials (`_section.html` is
  now a partial too) with `can_edit` off, plus Comments for a day or section. A **meal has its own page** now,
  `trips:meal_edit` / `meal_delete` (`/trips/<pk>/days/<day_pk>/meals/<id>/`; confirmations and contacts & info like a
  leg's; the day page's Meals formset still edits them together). `section_edit` / `section_delete` honour `next`.
  Panel URLs carry a query string, so the offline worker never caches them; every item page still works on its own.
- **+ Add and five kinds** (day-first plan P3): each open day on the trip page ends, for editors, with **+ Add to Day N**
  (`partials/_day.html`, a form with `data-quick-add`): one line, Enter (an `sr-only` first submit button, no kind) or a
  kind button (Travel / Stay / Do / Eat / Note; Options comes with P4) → `trips:quick_add` (`/trips/<pk>/days/<day_pk>/add/`,
  POST, editors). `apps/trips/quick_add.py` is pure (reuses `logistics`' arrow / mode / rough time): `parse(text, kind)` →
  `travel` (mode, origin / destination — "Train to X" leaves from the day's city —, `duration`, a typed time only as
  "Around 09:15" in its notes: a planned leg has no times), `stay` (name, `nights`), `eat` (meal type from the first word,
  else from the time; `time` = `reserved_time`), `do` (activity kind from the first word; `time` = `start_time`), else
  `note`. The view makes it on the day (cities matched like `leg_quick_add`, currency `default_for`, `order` last + 1,
  `trip_cities.sync`) and answers `{"url", "anchor"}` to `fetch` (`panel.js` refreshes the day and opens the item in the
  panel) or redirects to the item's page with `next` = the day. A new meal's page offers its catalogue match ("Looks like
  the catalogue place …", `catalogue_links.attach_suggestions`; `catalogue_link` now honours `next`), never links it.
  **Notes:** `Section.Type.NOTE` (trips 0048, choices only): title = optional heading, payload `{"tone": "" | tip | warning
  | critical, "paragraphs"}` (`NotePayloadForm`; a "• " paragraph is a bullet), drawn as a callout of `note_style`
  (`Section.NOTE_TONE_STYLES`: tip → info) or else like free text, on the page and in the booklet. Add to this day offers
  Note, Travel notes and Choose your adventure. **Converting** `Section.OLD_NOTE_TYPES` (phase, callout, free text):
  `apps/trips/day_first.py` (`plan` / `apply(trip, ids)`, one transaction, one history line; a phase's heading becomes
  the title, summary and highlights (as "• ") paragraphs; a callout's tone kept, info → tip; other payload keys kept) via
  `trips:trip_convert` (`/trips/<pk>/convert/`, editors, every row ticked; Needs attention's "N sections to turn into
  notes", counted from the prefetch), `manage.py convert_day_first --trip <pk> [--apply]` and `import_itinerary --apply`
  (a new trip's sections become notes; the parsers still emit the old types). Old types still render and edit. **Tidy**
  reads a note as what it replaced (`tidying._tidy_type`: a toned one-paragraph note as a callout, a heading-only one as a
  phase, else free text) and applies to it (`_callout_text`, paragraphs for "text" / "summary"). The booklet snapshot's
  fixture converts its phase, callout and free text: only the phase's highlights changed, from a list to "• " lines.
- **"Choose one" groups and votes** (day-first plan P4; trips 0049, which depends on accounts 0019): `OptionGroup`
  (trip, day — a stay group on its first night —, `prompt`, `notes`, `start_time` (places it in the timeline), `order`,
  `state` open / picked / split, `decided_by` / `decided_at`; `pick(option, user)` / `reopen()`, and an open group's
  `save()` clears its chosen option), `Option` (group, title, notes, url, `est_cost` + currency, order, `chosen` — one
  per group, `option_one_chosen` —, `travelers` — who takes it in a split) and `Vote` (user + option, `vote_once_per_option`). Every leg,
  stay, trip activity, meal and section has an optional `option` FK (SET_NULL: deleting a group leaves its items on the
  day). **What counts:** an item outside any option or in a chosen one (`options.counts`; `models.counts_q()` as a
  filter). `apps/trips/options.py` `attach(trip, days, viewer)` (3 queries: groups, options, votes with users) runs first
  in `_trip_page_context` and `trip_pdf` and takes the other items out of the prefetched lists (`trip.transport` /
  `lodging` caches, `day.ordered_*`), so the timeline, Not booked yet, the estimate, the day summary and everything after
  see only what counts; it gives each option `items`, `vote_count`, `voters`, `voted`, `cost` (option + activities +
  legs, in their currency when one, else home via `budget.rates_for`) and `duration`, each day `open_groups` /
  `picked_groups`, and chosen items `chosen_from`. `count_on_days` adds an open group to the day's ⚠; the banner's
  "N decisions" = open decision tasks + open groups (links to the first group). The calendar feed, the map, the public
  view and `audit_public_leak` filter with `counts_q`; the feed adds one all-day "Undecided: A / B" per open group. The
  trip page pin is 36 (groups, options, the options' travellers (P5), votes; an option mixing currencies adds the two
  rate queries once); the estimate adds chosen and split-taken options' own `est_cost`. **Page:** `partials/_option_group.html` (a box: options, their
  items through the usual rows, cost, time, 👍 for `comment`, Pick for editors; timed groups sit in `itinerary.timeline`
  as kind "group", others after it as `day.untimed_groups`) and `_picked_group.html` ("Chosen from: … — X", Considered,
  Reopen). **Views:** `trips:option_vote` (POST toggle, `comment`, 204 for fetch), `option_pick` / `group_reopen`
  (editors), `group_new` / `group_edit` (`/trips/<pk>/days/<day_pk>/choices/new/`, `/trips/<pk>/choices/<id>/`:
  `OptionGroupForm` + `OptionFormSet`, then per option its items and a one-line add into it — `quick_add` with `option=`)
  / `group_delete`; `+ Add`'s **Options** button and the day page's **+ Choose one** make a group. Items join an option
  from their own form's **In option** (`forms.InOptionMixin`: the options of its day's groups; the field is dropped when
  the day has none, so pages that had no groups keep their query counts; the meal page uses `MealPageForm`, the day's
  Meals formset doesn't). `OptionGroup` is in `changes.TRACKED` ("choice": prompt, decision, time); undoing a pick
  reopens, undoing a reopen isn't offered. The To do page lists open groups first; new to-dos can't be "decide" (an
  existing decision keeps its kind and options page). **Booklet:** an open group prints "Prompt — undecided" with each
  option and its items; a picked one prints "Prompt: chosen (cost — notes)" and its items with the day's. **Converting**
  (`day_first`, the same review page, now keyed `section-<id>` / `task-<id>`): choose-your-adventure sections → groups
  (prompt, summary → notes, options with description + duration · cost as notes; comments and contacts move to the
  day; one with a confirmation is left alone and says so) and open decision to-dos with options → groups on the task's
  day, else its item's, else Day 1 (flagged), the chosen option picked, the task ticked off with "Moved to the choice …".
- **Split** (day-first plan P5; no migration): `OptionGroup.split(tracks, user)` (option → travellers; state `split`,
  nothing `chosen`) from `trips:group_split` (`/trips/<pk>/choices/<id>/split/`, editors; `forms.SplitForm`: a radio row
  per person on `day.roster`, everyone placed once, at least two options taken — else "pick it instead"; prefilled, so
  it also changes a split; linked as **Split** on an open box and the group page, **Change who goes** on a split one).
  An option someone takes in a split counts (`options.taken`; `counts_q()` adds `group.state == split` with an `Exists`
  on its travellers), so Not booked yet, the estimate and the map add every track. `options.attach` gives a split group
  `tracks` (taken options, `who` "Debbie, John") and `considered`, files the tracks' items in `option.items` and marks
  them `item.track`, moves a track's notes out of `day.ordered_sections`, and sets `day.split_groups`.
  `itinerary.timeline` keeps tracked items out of the shared timeline / Any time / Food ideas and adds the group as one
  entry (kind "split", at its `start_time` or its earliest item's; else `day.untimed_splits`); `itinerary.tracks(group)`
  gives each track `track_timeline` / `track_any` / `track_food`. `attach_stays` shows a tracked stay in its track on
  check-in and as `day.track_stays` ("Sleeping (Debbie, John): …") on other nights, never as `day.stay`. Page:
  `partials/_split_group.html` (columns from `sm`, stacked on a phone). Booklet: `pdf.booklet_context` sets
  `day.shared_legs` / `shared_activities` / `shared_meals` (tracked items out of the day's tables) and
  `pdf/_track.html` prints each track — a two-column `.tracks` table for two, stacked `.option`s for more; the
  snapshot fixture splits Day 4's afternoon between Ada and Bo. History: summary "split: Debbie → Castle; …"; undo
  reopens.
- **Ideas shelf** (day-first plan P6; trips 0050, bucketlists 0007/0008): `TripIdea` (trip, `title`, `notes`, at most one
  of `city` / `poi` / `activity` / `event` — `tripidea_one_target` —, `kind_hint` travel / stay / do / eat, `added_by`,
  `placed` = generic link to the item or `Option` it became; on the shelf while `placed_id` is null). `Vote` now has
  `option` or `idea` (`vote_one_target`, `vote_once_per_idea`). `apps/trips/ideas.py`: `load(trip, viewer)` (two queries,
  `trip_detail` only, so the day fragment's pin is unchanged), `idea.kind` (its hint, else from the link: a `food` place
  → eat, event / activity / place → do, else note), `fill(idea, item)` (catalogue place — venue for an activity or event
  —, event, city and notes onto the item), `counted(trip)` (ideas placed on something that counts, P4/P5's rule),
  `return_to_shelf` (a `post_delete` on legs, stays, activities, meals, sections and options clears `placed`),
  `map_features` (the map's **Ideas** layer: faint `marker: "idea"` pins for shelf ideas with a place, switch off by
  default). Views in `idea_views.py`: `idea_add` / `idea_vote` (`comment`), `idea_edit` / `idea_delete` (its adder while
  they may comment, editors any), `idea_place` (editors; a day and a kind → `views._make_on_day`, + Add's builder, then
  `fill`; JSON for fetch like + Add), `idea_option` (editors; `target` = `group-<id>` an open group or `day-<id>` a new
  "<title> or …" group; a catalogue-linked idea also gets its item inside the option), `idea_from_catalogue`
  (`/trips/ideas/from/<poi|city|activity|event>/<pk>/`: the member's unfinished trips they may comment on; one idea per
  target per trip). Page: `trips/partials/_ideas.html`, the fold after About this trip (`#ideas`, `#idea-N`); goals'
  owners through the shell partial `partials/_idea_goals.html` (loads `bucketlists:idea_goals` JSON after the page:
  "Debbie's goal"); **Save for someday** (shell partial `partials/_save_idea.html` → `bucketlists:save_idea`, on shelf
  ideas and Considered options: the target, else the title; refused when already on the list); **Add to a trip** on
  place / city / activity / event pages (shell partial `partials/_trip_add_button.html`, `url … as`). Ideas join
  `changes.TRACKED` ("idea": title, notes) and the Your data export; never public, not in the booklet or calendar.
  `bucketlists:trip_done` offers only goals whose idea is `counted` (or linked without an idea).
- **Edit this day** (trip-page UX plan, U5): each day on the trip page has an "Edit this day" link for
  editors to `trips:day_edit` (opened in the panel, P2), the day's workshop and the no-JS place where things on a day
  are added: **Add to this day** (first the one-line + Add, as on the trip page (P7); then a leg via the inline quick add, a stay, an activity, a meal via the meal formset
  `#meals`, a section — Note, Travel notes, Choose your adventure (P3) — and a contact or note for
  the whole day; a to-do from its item's page), **On this day** (`views._day_workshop`: the day's stays — Check out / Check in / Sleeping —
  then the day's items in the trip page's order —
  `itinerary.timeline`, then sections, then food ideas — each with its confirmation numbers and linked
  contacts/notes and Edit / Confirmations / Contacts & info, via `partials/_workshop_row.html`; every
  link comes back to the day page), then the day details and meals form. Saving the day returns to
  `next` when it's on this site (Settings' days table passes its own address), else to
  `trip_detail#day-N`, which opens that day (`views._day_back`). Saving a section returns to the day
  page's `#on-this-day`.
- **Tidy suggestions** (trip-page UX plan, U7; trips 0033 `TidyDismissal`): `apps/trips/tidy.py` is pure
  (no Django) and takes a plain snapshot (`tidying.snapshot(trip)`); it suggests where text repeats
  something that has a home: a narrative line naming the day's leg / stay / meal / activity
  (`repeats_item`), a "Book…" callout repeating an open task (`callout_task`: delete it, or keep it as an
  info note on the task's item), a phone number in text or trip notes (`phone` → a contact linked to the
  named meal/section; a "name / notes / Phone:" block in the trip notes becomes one contact), trip notes
  repeating legs/stays or listing numbered options (`notes_repeat`, `notes_options` → a decision task),
  a logistics table titled like an activity (`table_activity` → an info note on it), "Day N" written
  on another day (`day_slip`, flag only) and an empty phase that is only "<time> — Dinner" next to the day's
  one meal of that type (`meal_phase`: give the meal that `reserved_time` — `tidy.clock_time`, am/pm from the
  meal type when missing — and delete the phase; review only) and a callout naming a place / activity / event linked on
  that day — the items' own links plus an event's activity and venue and an activity's venue (`catalogue_note`,
  catalogue-notes N5: "Move it to the catalogue" creates a `CatalogueNote` on it — pending and submitted for review,
  published when staff apply it; tone from the callout — and deletes the section; `tidying.apply(…, user)`; review
  only). **High confidence** only for kinds 1–2 when the item *leads*
  the line (after an optional "Lunch:" label, followed by a dash/bracket/end — not "Borough Market →
  Tate Modern") or the callout's title says Book/Reserve/Critical. **Suggestions only**: the review page
  `trips:trip_tidy` (`/trips/<pk>/tidy/`, editors; linked from the trip page's ⋯ menu) shows them by
  day, unticked, with before → after; `tidying.apply` runs the ticked ones in one transaction,
  re-checking each against the current text (a stale one is skipped and reported); "Not this" stores a
  `TidyDismissal` (the suggestion's stable key). `manage.py tidy_trip --trip <pk> [--apply]`: dry run
  lists everything; `--apply` applies only high-confidence kinds 1–2, never phones, notes, tables or
  slips. No detection runs on the trip page.
- **Decisions are tasks with options** (trip-page UX plan, U6; trips 0032; superseded by "choose one" groups in day-first
  P4 — new to-dos can't be decisions and the review page converts old ones): `BookingTask.kind` is
  `book` (default) or `decide`; a decision's `TaskOption`s (title, detail, url, est_cost + currency,
  order; at most one `chosen` per task — partial unique index `taskoption_one_chosen`) are edited on
  `trips:task_options` (`/trips/<pk>/tasks/<id>/options/`, editors; saving options makes a task a
  decision; the chosen radio is separate from the rows). Reference → Still to book shows "Decide: …"
  with its options (chosen ✓) and Needs attention counts decisions; the booklet prints them too.
  Choosing creates nothing: `trips:option_add` redirects to the day's new-stay page (the task's day, else
  Day 1) or new-activity page, pre-filled (`?from_option=`);
  nothing is saved until that page is. The trip page prefetches `booking_tasks__options` (one query).
- **Contacts and info notes link to items** (trip-page UX plan, U4; trips 0031): `TripInfo` (trip-wide
  know-how: title, body paragraphs, url, order) and `Contact` (now with `address`, `url`) are the
  *sources*; `ItemLink` links one to a *target* of the same trip — a leg, stay, activity, meal, a
  day's section, or the day itself (`models.LINK_SOURCES` / `LINKABLE`; generic keys on both ends,
  `ItemLink.link()` checks the trip, once per pair; `GenericRelation`s on both ends delete links with
  either). `itinerary.attach_links` resolves the trip's prefetched `item_links` (two fixed queries
  with `infos`): `item.refs` (a one-line ☎ with tel:/mailto:, or an ⓘ that expands, via
  `partials/_refs.html`, on each item's row/card; a stay's contact also on every "Sleeping" line),
  `day.good_to_know` (linked to the day or its sections) and each source's `on` ("On: Day 5 · …"
  links). Reference → Contacts (`#contact-N`) and Info (`#info-N`) are their homes. The booklet prints
  them in full where they surface and in Reference (Contacts, Info). Editing: the **Contacts & info**
  block (`partials/_item_links.html`, `trips:item_links` `/trips/<pk>/links/<kind>/<id>/`: attach one
  the trip has, create a contact or note on the spot, or remove — never deletes) on the leg and
  stay and activity pages and reached from the day page (sections, meals, the whole day)
  and the section page; each contact/note has its own page with ticks for its items
  (`trips:contact_new/edit/delete`, `trips:info_new/edit/delete`, `forms.linkable_choices`); Settings
  lists them under Contacts & info. Never public;
  `trip_leak_finders` also forbids contact phones and emails.
- **Day assembly is shared** (`apps/trips/itinerary.py`, trip-page UX plan U1): pure functions over
  the trip page's prefetch, used by both the web page and the booklet — `place_legs` (legs per day,
  placement, `travel_total`, stray legs), `timeline` (U3: a day's timed items, Any time, Food
  ideas), `attach_links` / `anchor` (U4), `overview` / `open_day` (U2) and `attach_stays` (`day.stay` = where you sleep that night,
  `checking_in` / `checking_out`). Put new per-day derivations there, not in a view or a template.
- **The booklet is snapshot-guarded:** `tests/test_booklet_snapshot.py` renders the booklet HTML for a
  fixture with every item kind and compares it to `tests/snapshots/booklet.html` (whitespace
  collapsed; no database ids in it). Web changes must leave it alone; when a phase deliberately
  changes the booklet, rerun with `UPDATE_SNAPSHOTS=1 python manage.py test
  apps.trips.tests.test_booklet_snapshot`, review the diff and commit the snapshot.
- **PDF booklet:** "Download PDF" on the trip page → `trips:trip_pdf` (`/trips/<pk>/booklet.pdf`), anyone
  who can see the trip, never public (it has confirmation numbers). Its own print template
  `trips/pdf/booklet.html` (US Letter, running header with trip and day, page X of Y; cover, days at a
  glance, one section per day with its stay, legs, sections and meals, then confirmations / stays /
  contacts / still to book) rendered by WeasyPrint (`apps/trips/pdf.py`), from the same prefetch as the
  trip page (`views._trip_page_queryset`). WeasyPrint needs `libpango-1.0-0 libpangoft2-1.0-0
  libharfbuzz-subset0` on the server; without them the view says so and redirects (`PdfUnavailable`)
  instead of a 500. Pictographic emoji are stripped (no emoji font on the servers).
- **URLs:** `trips:` at `/trips/` (list, `<pk>/`, `new/`, `profile/`, days, sections, comments);
  `trips_staff:dashboard` at `/staff/trips/`, gated by `User.can_access_staff`. The user admin
  with role and trip-access inlines is registered from `apps/trips/admin.py`.
- Management commands: `import_itinerary` (docx, dry run unless `--apply`), `dedupe_travelers`,
  `audit_public_leak`, `unescape_html`. Tests: `python manage.py test apps.trips` (the whole suite, in parallel, takes
  about 70 seconds).

## Dependency layers

The goal is that any app can be lifted into another project by taking it plus the layers below it.
What makes that possible is the direction of imports. Apps live in `apps/` and import each other
as `apps.<name>`; James's other Django projects (e.g. SoHo) use the same `apps/` convention, so a
lifted app dropped into another project's `apps/` keeps working without import rewrites.

**Imports only point down this list.** An app may import from its own layer only when the order
inside the layer allows it (listed left to right; a later app may import an earlier one). Names
in the table are app labels; the code is at `apps/<label>/`.

| Layer | Apps | May import |
|---|---|---|
| 0. Base | `core` | nothing local — Django and third-party only |
| 1. Identity | `accounts` | `core` |
| 2. Platform services | `notifications`, `media_app`, `approval_system`, `rewards` | layers 0–1 (`approval_system` → `notifications` is allowed) |
| 3. Catalog | `locations`, `activities`, `vendors`, `events`, `catalogue_notes` | layers 0–2; within the layer: `activities` → `locations`; `vendors` → `locations`; `events` → `locations`, `activities`; `catalogue_notes` → `locations`, `activities`, `events` |
| 4. User content | `bucketlists`, `trips`, `reviews`, `recommendations` | layers 0–3; within the layer: `bucketlists`, `reviews` and `recommendations` → `trips`; `bucketlists` → `reviews` |
| 5. Site | `pages`, `admin_tools` | anything |

`theme` (django-tailwind) and `config` sit outside the ladder and outside `apps/`.

Rules that follow from this:

- **Never `from apps.accounts.models import User` outside `accounts`.** Models use
  `settings.AUTH_USER_MODEL` in the FK; code uses `django.contrib.auth.get_user_model()`. An app that
  imports the concrete `User` can only ever run inside this project.
- **A cross-layer FK pointing up is a design error, not an import problem.** A string reference like
  `"trips.Trip"` hides the import but still makes the lower app's migrations depend on the higher one.
  If a lower model needs to know about a higher one, put the FK on the higher model, or use a
  `GenericForeignKey`, or a signal.
- **Pin `label` in every `apps.py`** (`name = "apps.trips"`, `label = "trips"`). The label decides table
  names, content types and migration history; pinning it is what made the move into `apps/`
  data-neutral, and keeps any later move data-neutral too. Most models here already set `db_table`
  explicitly — keep doing that for new models.
- **Always import other apps absolutely as `apps.<name>`.** Relative imports are fine inside one
  app; no `sys.path` tricks, no bare `from trips…`.
- **Each app ships its own templates** under `apps/<app>/templates/<app>/`; only the shell
  (`base.html`, `partials/`, `components/`) lives in the top-level `templates/`.
- Keep `docs/architecture/app_dependencies.md` (arrows mean "imports") and the `LAYERS` /
  `SAME_LAYER_ALLOWED` tables in `scripts/check_layers.py` in step with this table.

### Checking it

```bash
python scripts/check_layers.py      # exits 1 and lists each violation
```

It parses every app's imports under `apps/` with `ast` (migrations skipped) and flags upward imports,
same-layer imports not listed above, concrete `apps.accounts.models.User` imports outside `accounts`,
bare (un-prefixed) imports of a local app, and any Django app directory at the repo root other than
`config` and `theme`. `apps.core.tests.test_layers` runs it, so `manage.py test` fails on a violation.

The violations found at commit `ddd00d7` (`core` → `accounts`/`trips`/`bucketlists`, `accounts` →
`locations`, ten concrete `User` imports) were fixed in Phase 0.5.

## Work plan

Two pieces of work, in this order: tidy the dependency layers (Phase 0.5), then merge the
itinerary app into this project (Phases 1–4), with the move into `apps/` (Phase 3.5) between
styling and integration. Work on a branch; do one phase per branch/PR. Completed phases below are
kept as history and describe the flat layout as it was at the time; their paths are not current.

**Decisions** (1–3 answered 2026-10-07: 1 = nothing to keep, drop and replace; 2 = no outside users or production database, migration history may be reset; 3 = move the role onto `TripGrant` per trip, as its own step after Phase 1). **Still open — stop and ask James before the step that depends on it:**

1. Does anything in this project's current `trips*` tables need keeping? (Decides whether
   Phase 1 is drop-and-replace or needs a data migration.)
2. Does this project have outside users or a production database? (Decides whether
   migration history can be reset in Phase 1.)
3. ~~Trip access model~~ — done on branch `phase-1b-grant-roles`: role per `TripGrant`;
   `creator` stays app-wide; sharing (grant management) stays staff-only for now.
4. ~~Rewards~~ — answered 2026-10-18 (R11): one membership model, `trips.RewardsMembership` keyed to
   `Traveler`, linked to the `rewards` catalogue (`rewards` can't point at `Traveler`: it's a lower layer).
   Phase 4 only.

### Phase 0 — prep

Status: done. Django is on 6.1.2; both databases were dumped to `~/db_backups/*_20261007-133218.dump` (custom format, restore with `pg_restore`).

- `pg_dump` both databases before anything else (this one's container, and `itinerary` on
  `localhost:5432` — command in the itinerary CLAUDE.md under "Database").
- Upgrade Django 6.0.1 → 6.1.x (itinerary is on 6.1.1); `manage.py check` clean.

### Phase 0.5 — dependency layers

Status: steps 1–6 done on branch `phase-0.5-layers`; `check_layers.py` is clean.

Smallest useful set; each is independent and can be its own commit.

1. Create `pages` (`python manage.py startapp pages`); move the views from `core/views.py` that
   touch other apps, with their URLs and templates. Keep URL names working (namespace `pages:`
   plus redirects or updated `{% url %}` tags — grep templates for `core:`).
2. Replace the `Country`-based currency choices in `accounts/forms.py`.
3. Switch the ten concrete `User` imports.
4. Pin `label` in every `apps.py`.
5. Add `scripts/check_layers.py`: encode the layer table above, parse imports with `ast`
   (skip `migrations/`), exit 1 on an upward import. Run it from a test in `core` too, so
   `manage.py test` fails on a violation.
6. Update `docs/architecture/app_dependencies.md`.

Leave the bigger decoupling (catalog apps, `approval_system` ↔ `notifications`) until after the
merge, when there are tests to lean on.

### Phases 1–4 — merging the itinerary app

The itinerary project (`~/projects/itinerary/code`, repo `jjennings308/itinerary`) is a separate
Django 6.1 app whose `trips` app is far more developed than ours: real trip data (Taos, Europe
2027), 13 migrations, and a full test suite. **Its `trips` app replaces ours.** Its CLAUDE.md is the
reference for how that app works; read its sections on access, the public view, time zones and
transport legs before changing anything in them, and carry those sections into this file when the
merge lands.

Why the two cannot simply coexist:

- **App label `trips` in both.** Table names don't clash (ours use `db_table` = `trips`,
  `trip_days`, …; theirs are `trips_trip`, `trips_day`, …), but one project cannot have two apps
  with one label or two migration histories under it.
- **App label `accounts` in both.** Theirs holds only `UserRole`.
- **User model.** They use stock `auth.User`; we use `accounts.User`. Every user FK on their side
  (`TripGrant.user`/`granted_by`, `Trip.created_by`, `Comment.author`, `Traveler.user`,
  `UserRole.user`) must point at `settings.AUTH_USER_MODEL`. Check their migrations for a literal
  `'auth.user'`.
- **URL namespace `trips:`** and template names (`trips/trip_detail.html`, `trip_form.html`,
  `dashboard.html`) in both.
- **CSS.** DaisyUI here already defines `.card`, `.badge`, `.btn`, `.hero`, `.avatar`, `.alert`,
  `.stat`, which their component layer also defines.

**Phase 1 — replace `trips` (lift and shift).** Status: done on branch `phase-1-trips`; dev
DB migrated, all 518 tests pass. Auth tests moved to `accounts/tests/test_auth.py`; password
change pages added to `accounts`; staff-lands-on-dashboard login behaviour dropped.


- Remove our `trips` app. What imports it today: `reviews/models.py` (FK; and
  `reviews/0001_initial` depends on `('trips', '0001_initial')`), `recommendations/models.py`,
  and the views that move to `pages` in Phase 0.5. Repoint them at the new `Trip`.
- Copy their `apps/trips` in as `trips/` (flat). Rewrite `apps.trips.` → `trips.` in imports
  **and** in serialized paths inside migrations (e.g. `apps.trips.models.validate_timezone_name`).
  Leave `to='trips.day'`-style references alone — they resolve by label. (Phase 3.5 reverses the
  prefix rewrite.)
- Move `UserRole` into our `accounts` as a new migration; rewrite `from apps.accounts` imports.
  Their rule that `accounts` never imports `trips` still holds and matches the layer table.
- Their `ItineraryUserAdmin` re-registers contrib's user admin to add inlines. Instead, add the
  role and trip-grant inlines to our `User` admin — registered from `trips/admin.py` (unregister,
  subclass ours, register), so `accounts` still does not import `trips`.
- Drop their `RoleAwareLoginView` and `registration/` templates; use our login
  (`EmailOrUsernameBackend`). Keep the behaviour that `?next=` wins. Repoint their password
  reset/change tests at our URLs.
- Their staff `/dashboard/` moves under `/staff/` and is gated by `can_access_staff_dashboard`,
  not `is_staff`.
- Their `/profile/` (traveler profile) must not clash with our account pages; mount it under
  `/trips/profile/` or link it from account settings.
- Templates extend our `base.html`.
- Migration history (dev DB, assuming Decision 1 = nothing to keep): drop our `trip*` tables,
  delete `django_migrations` rows for app `trips`, apply their `0001`–`0013`. `reviews` and
  `recommendations` then need fresh migrations because their FK constraints point at the old
  `trips` table. Run `remove_stale_contenttypes` afterwards.
- Their management commands come along unchanged: `import_itinerary`, `dedupe_travelers`,
  `audit_public_leak`, `unescape_html`.
- Done when their whole test suite passes under `config.settings.dev`.

**Phase 2 — move the data.**

Status: done 2026-10-07. 250 objects loaded (2 trips, 7 travelers, 7 grants, 6 roles, no
comments); accounts debbie, henry, john, regan and sara created with their itinerary password
hashes. Accounts with no email got `<username>@noemail.invalid` placeholders (`User.email` is
unique here) — replace them in the admin. Row counts match, both detail pages render,
`audit_public_leak` exits 0; neither trip had a public token. Backup taken first:
`~/db_backups/travel_site_pre_phase2_20261007-145050.dump`.


- Create `accounts.User` rows for their six people and `admin` with the **same usernames**.
- `dumpdata trips accounts.userrole --natural-foreign --natural-primary` from itinerary,
  `loaddata` here. Natural keys carry `Comment.content_type` and user FKs by username.
- Do **not** rebuild from `.docx` with `import_itinerary` — that discards every admin edit made
  since the original import.
- Verify: row counts per table match, every trip detail page renders, the detail page stays at
  19 queries (see the Trips section), `audit_public_leak` exits 0, existing `public_token` links resolve.

**Phase 3 — styling.** Status: done on branch `phase-3-styling` (scoped under `.trips-ui` rather than renaming classes, so no test changes). Remaining: compare a browser-printed trip PDF against the itinerary site by eye; the itinerary's own npm build and `app.css` retire with that repo (Phase 4).


- Port their component layer (`.card`, `.chip`, `.callout*`, `.badge-*`, …) and the
  `@media print` rules into `theme/static_src/src/styles.css`; map their `accent` tokens onto the
  earth palette. Their print output is the deliverable (trips are printed to PDF) — compare a
  printed trip before and after.
- Resolve the DaisyUI class collisions by prefixing one side. Their tests assert some class names
  (`callout-warning`, `badge-critical`), so a rename updates those tests too.
- Add the trips templates to the Tailwind `@source` globs; retire their standalone npm build and
  `static/css/app.css`.

**Phase 3.5 — move every app under `apps/`.** Status: done on branch `phase-3.5-apps-dir`. All step 10 checks hold: no migration changes, `showmigrations` identical, no stale content types, CSS hash unchanged, `audit_public_leak` 0, layer check clean (it now also flags root-level apps and unprefixed local imports). The `staticfiles/` refresh it turned up (Django 6.1 admin CSS, rebuilt Tailwind, one never-collected SVG) is committed separately; none of it came from the move.

Do it before Phase 4: Phase 4 adds cross-app FKs and imports, and every one of those would
otherwise need rewriting. The move is a **code-only change**. Labels are pinned (Phase 0.5 step 4)
and most models set `db_table`, so table names, `django_migrations` rows, content types,
permissions, `AUTH_USER_MODEL`, `"label.Model"` FK strings, URL namespaces, template names, tag
libraries and management command names all stay the same. Only Python module paths change
(`trips.views` → `apps.trips.views`). If any step suggests a database change, stop and ask James.

What moves: every directory at the root with an `apps.py` — `core`, `accounts`, `notifications`,
`media_app`, `approval_system`, `rewards`, `locations`, `activities`, `vendors`, `events`,
`bucketlists`, `trips`, `reviews`, `recommendations`, `pages`, `admin_tools`, plus any other app
found. What stays at the root: `config/`, `theme/` (django-tailwind finds it by
`TAILWIND_APP_NAME = "theme"`), `templates/`, `scripts/`, `docs/`, `staticfiles/`, `manage.py`.

1. **Baseline.** Start from a clean tree on the new branch. Take a `pg_dump` to
   `~/db_backups/travel_site_pre_phase3.5_<timestamp>.dump` (nothing should write, but it's cheap).
   Record, for comparison at the end:
   - `python manage.py showmigrations > /tmp/sbl_showmigrations_before.txt`
   - `sha256sum theme/static/css/dist/styles.css`
   - `python scripts/check_layers.py` is clean and the full test suite passes (518 tests).
   - Confirm every `apps.py` has an explicit `label`. If one doesn't, stop and ask — moving
     it would change its label.
2. **Move.** `mkdir apps && touch apps/__init__.py`, then `git mv <app> apps/` for each app.
   Commit this as a pure-move commit (the tree won't run yet) so `git log --follow` keeps history.
3. **`apps.py`.** In each, change `name = "<x>"` to `name = "apps.<x>"`. Do **not** touch
   `label`.
4. **Settings** (`config/settings/base.py`, and check `dev.py` / `prod.py`). Prefix module paths
   with `apps.`: `INSTALLED_APPS` (keep whichever form each entry uses — `"apps.trips"` or
   `"apps.trips.apps.TripsConfig"`), `MIDDLEWARE`, `TEMPLATES[...]["OPTIONS"]["context_processors"]`,
   `AUTHENTICATION_BACKENDS`, and any other dotted path (logging handlers/filters, form renderer,
   third-party settings). Leave `AUTH_USER_MODEL = "accounts.User"`, `TAILWIND_APP_NAME`,
   `ROOT_URLCONF`, `WSGI_APPLICATION`, and URL-name settings (`LOGIN_URL` etc.) alone.
5. **Imports and dotted-path strings in code** (everything except migrations). List hits with:
   ```bash
   APPS="core|accounts|notifications|media_app|approval_system|rewards|locations|activities|vendors|events|bucketlists|trips|reviews|recommendations|pages|admin_tools"
   grep -rnE "^\s*(from|import) ($APPS)(\.|\s|$)|[\"']($APPS)\.[a-z_]+(\.[a-z_]+)*[\"']" \
     --include=*.py --exclude-dir=migrations --exclude-dir=.venv --exclude-dir=node_modules apps config scripts
   ```
   - Rewrite `from <x>…` / `import <x>…` to `apps.<x>…`, including `AppConfig.ready()` signal
     imports, `include("<x>.urls")` in `config/urls.py` and any app `urls.py`, and
     `mock.patch("<x>.…")` targets in tests.
   - For quoted strings, rewrite **only module paths** (Django imports them):
     `"trips.urls"`, `"core.middleware.UserTimezoneMiddleware"`. **Leave label lookups alone**:
     `"trips.Trip"`, `apps.get_model("trips", "Trip")`, permission strings such as
     `"accounts.can_access_staff_dashboard"` (lowercase, but a label + codename, not a module),
     `"pages:home"`, `"trips/trip_detail.html"`. Decide each string by what Django does with it,
     not by its shape; don't run a blind `sed`.
   - Relative imports within one app stay as they are. Add no `sys.path` changes.
   - The grep above misses path segments that start with a digit: `test_planning.py` loads
     `"trips.migrations.0004_…"` with `importlib.import_module`, and only the test run caught it.
     Also grep for `import_module(` / `import_string(`.
6. **Migrations.** Grep `apps/*/migrations/*.py` for serialized module paths and rewrite them
   to `apps.<x>.…`:
   ```bash
   grep -rnE "^\s*import ($APPS)\.|\b($APPS)\.(models|utils|validators|fields|managers|storage)\b" apps/*/migrations/
   ```
   Typical hits: `import trips.models` with `trips.models.validate_timezone_name` (Phase 1 rewrote
   these from `apps.trips.` — this reverses it), `upload_to=` / `default=` callables, custom fields,
   `managers=[…]`, and non-model mixins in `bases=(…)`. Leave `to="<label>.<model>"`,
   `dependencies=[("<label>", "…")]` and `swappable_dependency(settings.AUTH_USER_MODEL)` alone.
   Do **not** regenerate, squash or reset migrations, even though Decision 2 allows it — it isn't
   needed, and it would put the data loaded in Phase 2 at risk.
7. **Tailwind.** In `theme/static_src/src/styles.css`, change the per-app `@source` globs to
   cover `apps/*/templates` (paths are relative to that file, so mirror the existing pattern, e.g.
   `@source "../../../apps/*/templates";`). Keep the top-level `templates/` glob. Run
   `python manage.py tailwind build`; the dist CSS should hash the same as the baseline. A
   difference means a template directory is no longer scanned — fix the glob and don't commit until
   the hash matches (or the diff is explained).
8. **Tooling, scripts and docs.**
   - `scripts/check_layers.py`: discover apps under `apps/`; map imports of `apps.<x>` to `<x>`
     for the `LAYERS` lookup (keep `LAYERS` keyed by label); match the concrete-`User` rule on
     `apps.accounts.models`; flag bare `import <x>` / `from <x>` of a local app; and flag any
     Django app directory (one with `apps.py`) at the repo root other than `config` and `theme`.
     Its test is now `apps.core.tests.test_layers`.
   - Grep `pyproject.toml`, `setup.cfg`, `.coveragerc`, `.pre-commit-config.yaml`, `.vscode/`,
     `scripts/*.sh` and `Makefile` (whichever exist) for app names, and update first-party
     settings (e.g. ruff/isort `known-first-party = ["apps", "config"]`).
   - Update paths in `docs/architecture/app_dependencies.md` and any app-level docs that link to
     other apps' files (`apps/approval_system/*.md`, `apps/accounts/docs/`).
9. **Static files.** `python manage.py collectstatic --noinput`, then `git status staticfiles/`.
   Expect no changes, since app static files are namespaced inside each app's `static/` folder.
   Investigate any change before committing.
10. **Verify** — all of these must hold:
    - `python manage.py check` is clean.
    - `python manage.py makemigrations --check --dry-run` says *No changes detected*. If it
      proposes anything, stop: a label or `db_table` changed.
    - `python manage.py showmigrations` diffs empty against `/tmp/sbl_showmigrations_before.txt`.
    - `python manage.py remove_stale_contenttypes` finds nothing to remove. If it lists anything,
      answer **no** and stop.
    - `python scripts/check_layers.py` is clean.
    - The full test suite passes (518 tests, about 12 minutes), including
      `QueryCountTests` at 19 queries.
    - `python manage.py audit_public_leak` exits 0.
    - The step 5 and step 6 greps return nothing.
    - `runserver` smoke test: log in, then open the home page, dashboard, a trip detail page, the
      staff dashboard and the admin. Existing dev sessions are logged out by the move — each stores
      the old auth backend path `accounts.backends.EmailOrUsernameBackend` — so logging in again is
      expected, not a bug.
11. **Close out.** Set this phase's status to done in this file, remove the "if there is no
    `apps/` directory" note at the top, and confirm the paths in this file match the tree.

**Phase 4 — integrate (incremental, each its own PR).**

- `Trip` destination and `Day` city as FKs to `locations.City` / `Country`;
  `audit_public_leak` must stay green.
- Optional links from `Meal` / `Section` to `activities`, `vendors`, POIs.
- ~~Rewards consolidation (Decision 4)~~ — done in R11 (see Trips → Rewards programs); `TripExpense`
  reinstated on the new `Trip`; post-trip rating feeding `reviews`.
- ~~"Plan this" from a bucket-list item to a new trip~~ — done ("Plan a trip", branch `bucket-lifecycle`).
- ~~Retire the itinerary site~~ — R11 (2026-10-18): it never ran anywhere but this machine (no nginx
  site or service on tazcomputer; neither trip had a public link, so nothing to redirect). Nothing wrote to
  its database after the 2026-10-07 merge; final dump `~/db_backups/itinerary_final_20261018-182819.dump`.
  James decides on dropping the local `itinerary` database and archiving the GitHub repo.

### Trip items and confirmations

Plan: `docs/plans/trip-items-and-confirmations.md` (one record per trip item, shown in the
trip-wide lists and on its day; confirmations attached to the items they confirm). Phases A–F,
one branch each, in order; "Ask James" decisions there must be answered before the phase that
needs them. Status: Phase A (legs evolve in place, shown once in each view) done on branch
`phase-a-legs-in-place`; Phase B (confirmations attached to items, Quick reference generated) done
on branch `phase-b-confirmations`; Phase C (convert logistics tables into linked legs, trip-wide)
done on branch `phase-c-convert-tables`; Phase D (new itineraries start as legs) done on branch
`phase-d-new-itineraries-as-legs`; Phase E (booking tasks point at what they're about) done on
branch `phase-e-booking-tasks`; then confirmations were reworked to attach like comments
(`confirmations-generic`) and Phase F was replaced by `TripActivity` (`trip-activities`). Done.

### Trip page UX

Plan: `docs/plans/trip-page-ux.md` (the web trip page redesigned for the web — Overview,
collapsible days with a timeline, Reference — while the PDF booklet keeps its layout behind a
snapshot test; contacts and info notes linked to items; decisions as tasks; a content clean-up
review). Phases U1–U7, one branch each, in order. Decisions answered 2026-10-16. Status: U1–U7 done
(2026-10-16, branches `u1-booklet-guard` … `u7-tidy`); the plan's "Data to fix by hand" list remains.

### Help center

Plan: `docs/plans/help-center.md` (user guides as markdown files in `apps/pages/help/`, listed on
`/help/` and shown at `/help/<slug>/`; staff guides gated; "?" links from the trip and edit pages).
Phases H1–H4, one branch each, in order. Status: H1 (the machinery; `adding-a-day` moved in) done on
branch `h1-help-machinery`; H2 (`reading-your-trip`, `sharing-and-access`, `bookings-and-confirmations`)
done on branch `h2-help-machinery`; H3 (eight more guides, `adding-a-day` re-checked) done on branch
`h3-help-guides`; H4 (help links on the trip and edit pages) done on branch `h4-help-links`. Complete.

### Site roadmap

Plan: `docs/plans/site-roadmap.md` (editors invite people, production backups, error alerts and a
health check, calendar feed, tickets on bookings, offline trip page, change digest and history,
checklists, budget in one currency, phone pass and Phase 4 loose ends; plus James's no-code
checklist). Phases R1–R11, one branch each, in order; "Ask James" decisions there come first.
Status: R1 (editors invite people; the People page) done on branch `r1-trip-invites`; R2 (production backups on popsicletoes.us, restore drill) done on branch `r2-prod-backups`; R3 (error emails, `/healthz/`) done on branch `r3-alerts-health`; R4 (calendar feed) done on branch `r4-calendar-feed`; R5 (tickets and documents) done on branch `r5-booking-files`; R6 (offline trip page) done on branch `r6-offline-trip`; R7 (change digest) done on branch `r7-change-digest`; R8 (history and undo) done on branch `r8-change-history`; R9 (checklists) done on branch `r9-checklists`; R10 (budget in one currency) done on branch `r10-budget-currency`; R11 (phone pass, one rewards model, itinerary site retired) done on branch `r11-phone-pass`. The roadmap is complete.

### Trip days as the overview

Plan: `docs/plans/trip-days-as-overview.md` (drop the web trip page's Overview table; each folded day's
summary carries stay, travel, highlights and ⚠; Needs attention becomes a banner; travellers, cities,
notes and cost move to an "About this trip" fold; the booklet is unchanged). One branch,
`v1-days-as-overview`. Status: done (2026-10-23).

### Edit by day

Plan: `docs/plans/edit-by-day.md` (Edit trip keeps only trip-level things; stays, legs, to-dos and their
confirmations and contacts are added from the day or the item's own page; currency selects offer the trip's
home currency plus the local one; leg time zones and city choices filled from the catalogue; logistics tables
fold into travel notes). Decisions answered 2026-10-25. Phases E1–E6, one branch each, in order. Status:
E1 (stays added and edited from the day: `trips:stay_new` / `stay_edit` / `stay_delete`, `stay_form.html` with the
Confirmations and Contacts & info blocks and an "Adjust the pin" fold; the stay card's Edit link; option → new
stay) done on branch `e1-stays-from-day`; E2 (the To do page `trips:trip_todo` — open by priority then due date, done
folded, for everyone who can see the trip — and `task_new` / `task_edit` / `task_delete` / `task_done` for editors;
`BookingTaskForm(trip=…)` narrows its pickers like `ScopedBookingTaskFormSet`; `?leg=` / `?stay=` / `?activity=` pre-pick;
the leg, stay and activity pages' `partials/_item_todos.html` with "Add a to-do for this"; the banner's to do / decisions
and Reference's "All to-dos" link there) done on branch `e2-todo-page`; E3 (Edit trip without the Lodging, Transport,
Confirmations, Contacts and Booking tasks formsets — they and their classes are deleted — plus All stays & legs and
Loose confirmations; the trip's own rates on the Budget page; Edit trip 63 → 26 queries / 898 → 130 ms on Europe 2027)
done on branch `e3-slim-edit-trip`; E4 (home currency + currency choices, see Trips → Currency choices) done on
branch `e4-currency-choices`; E5 (leg zones and names from cities, This trip / Everywhere else city selects, a city
from elsewhere joins the trip) done on branch `e5-catalogue-fill`; E6 (Add to this day offers Phase, Callout, Free text,
Travel notes, Choose your adventure — `views._add_section_types`, no Logistics table; an old table's page has "Make it
travel notes", `trips:section_to_travel_notes`, which only changes its type) done on branch `e6-travel-notes`. Complete.

### Catalogue notes

Plan: `docs/plans/catalogue-notes.md` (notes on catalogue places, activities and events — tone, text, closed
weekdays, how far ahead to book — added by members and approved by staff, shown on the catalogue pages and under
every trip item linked to them, web and PDF; warnings for closed days and book-by dates; hide per trip; events on
trip items; a tidy suggestion to move a trip's place-specific callouts to the catalogue). Decisions answered
2026-10-26. Phases N1–N5, one branch each, in order. Status: N1 (notes on catalogue pages) done on branch
`n1-catalogue-notes`; N2 (notes on the trip page and in the PDF, Not for this trip) done on branch `n2-notes-on-trips`;
N3 (closed-day and book-by warnings, Add as a to-do) done on branch `n3-note-warnings`; N4 (trip sections and activities link to events, whose notes — and their activity's and venue's — come through)
done on branch `n4-events-on-trips`; N5 (the tidy suggestion to move a trip's callouts to the catalogue) done on
branch `n5-tidy-to-catalogue`. Complete.

### Day-first planning

Plan: `docs/plans/day-first-planning.md` (the trip page becomes the one place to read and edit — items open in a side
panel, + Add takes one line, five kinds of item; option groups inside a day with votes, pick and split; an Ideas
shelf linked to bucket-list goals; cities found by search, kept in step automatically and laid out by a route
builder; trip-wide pages become read-only views and Edit trip becomes Settings). Decisions answered 2026-10-26.
Phases P1–P7, one branch each, in order. Status: P1 (city search box and new cities, `trip_cities.sync`, the route
builder and strip) done on branch `p1-cities`; P2 (the item panel, `trips:day_fragment`, `trips:item_panel`, the meal's
own page) done on branch `p2-item-panel`; P3 (+ Add, notes, converting phases / callouts / free text) done on branch
`p3-quick-add`; P4 ("choose one" groups, options and votes; converting choose-your-adventure sections and decision
to-dos) done on branch `p4-option-groups`; P5 (split: tracks per traveller on the page, in the calendar's "only mine"
and in the booklet) done on branch `p5-split`; P6 (the Ideas shelf, Add to a trip, goals as ideas, Save for someday) done
on branch `p6-ideas`; P7 (Settings, fitting days to new dates, the Bookings page, To do with Not booked yet, trip-wide
views opening items in the panel) done on branch `p7-settings`. Complete.

### Rules carried over from the itinerary project

These bit that project once each; they apply here from Phase 1 on.

- **A migration whose FK points at the user must depend on accounts 0002 or later**, not only on
  `swappable_dependency(settings.AUTH_USER_MODEL)` (which means accounts 0001): the user table became
  `users` in 0002, and without it the migration's SQL names `accounts_user` (caught in R13 with `sqlmigrate`).
- **Read every `makemigrations` proposal for `RemoveField` / `DeleteModel` before applying it**,
  and confirm with `sqlmigrate` that a rename is a `RENAME`, not a `DROP`.
- **`manage.py shell` runs against the real database.** Take a `pg_dump` before any shell command
  that writes or deletes.
- **Never chain `|date` / `|time` after a time-zone filter.** Leg times render through their
  `at_zone` filters. Here it is worse than in itinerary: `UserTimezoneMiddleware` activates each
  reader's zone, so the mistake renders in the reader's zone instead of UTC and is harder to spot.
  Add a test with a non-UTC user.
- **Trip access goes through `Trip.objects.visible_to(user)` / `Trip.can()`** — 404 for no grant,
  403 for a refused action. `Trip.status` and `Trip.travelers` are never access checks.
- **A Django template comment or tag must not wrap onto a second line**; it is emitted verbatim.
