# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Layout:** Django apps live under `apps/` and are imported as `apps.<name>` (Phase 3.5).
> App *labels* (`trips`, `accounts`, …) are unchanged, so model references (`"trips.Trip"`),
> permissions, URL namespaces and template names use the bare name.

## Project

ShareBucketList (`SITE_NAME` in settings): a Django 6 travel site for bucket lists, trips, activities and locations. It uses PostgreSQL and server-rendered templates styled with Tailwind via `django-tailwind`. The site moved from Bootstrap to Tailwind; crispy-bootstrap5 in `INSTALLED_APPS` is a leftover.

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
scripts/           # check_layers.py, reset_db.sh
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

**Seed reference data** with the idempotent management commands in `apps/locations/management/commands/`. Run them in dependency order: `import_countries`, then `import_regions`, then `import_cities`, then `import_national_parks` / `import_sports_venues`, then `populate_flag_emojis`. Imported rows are marked approved automatically.

## Deploying (staging / production)

`config.settings.prod` refuses to start without a real `DJANGO_SECRET_KEY` (≥ 50 chars, not
`django-insecure…`) and `DJANGO_ALLOWED_HOSTS`. It assumes nginx terminates TLS and sets
`X-Forwarded-Proto` (`SECURE_PROXY_SSL_HEADER`), redirects to HTTPS, uses secure cookies, sets
HSTS to a year (`SECURE_HSTS_SECONDS`, default 31536000; use 3600 on a brand-new domain) and logs to stderr (systemd journal).
`security.W005` / `W021` (HSTS subdomains/preload) are silenced on purpose until HTTPS is proven on
the real domain. `django-browser-reload` is dev-only (`dev.py`; not in `requirements.txt`), and its
`/__reload__/` URLs exist only when it is installed.

**Live:** https://sharebucketlist.com on `james@tazcomputer.com` (shared Debian 13 box that also hosts
soho, score, tazcomputer, umami, excalidraw). Repo at `/var/www/travel_site` (owner www-data,
group-writable; `james` is in group www-data), gunicorn 2 workers as `travel_site.service` on
`/run/travel_site/travel_site.sock`, nginx site `/etc/nginx/sites-available/sharebucketlist.com`
(certbot TLS, `www` -> apex), Postgres 17 database/role `travel_site` on 127.0.0.1, outbound mail
via smtp2go. `sudo` there needs a password, so service/nginx changes are run by James.

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
- `config/urls.py` mounts each app under its own namespace (`pages:` for home/dashboard/about, `locations:`, `activities:`, `trips:`, `bucketlists:`, `events:`, `rewards:`, `staff:`) with `include("apps.<name>.urls")`. Use namespaced names with `reverse` and `{% url %}`. `apps.accounts.urls` (login, register and so on) is not namespaced. Staff-only views live in `apps/accounts/staff_urls.py` under `/staff/`. `/staff/` itself is the **staff dashboard** (`pages:staff_dashboard`, `apps/pages/staff.py`, gated by `User.can_access_staff`, linked from the header user menu): site stats plus a "needs attention" list (pending approvals vs the `ApprovalSettings.review_sla_hours` target, role requests, events with an unlisted city, cities missing a region, yearly activities with no upcoming event, unlinked activity places, leftover HEIC media, placeholder emails, legal placeholders). Add new staff to-dos there as another entry in `_attention()`. **CSV import/export** (`/staff/import/`, `admin_tools:import`, same gate): upload countries, regions, cities, places (POIs), activities or events (in that order; each looks up the earlier ones) → preview (new / update / error per row, nothing saved) → confirm; templates at `admin_tools:import_template`; `admin_tools:export` (and `manage.py export_catalogue [dir]`) writes the published items in the same columns, so an export can be edited and re-imported. `apps/admin_tools/importers.py` describes each kind once in `KINDS` and maps columns to the normal `ActivityEditForm` / `EventForm` (locations use small model forms there) (names looked up for category, country, region, city, activity) so imports obey the same validation; an activity matches by name, an event by name + start date, a country by ISO code, a region by name within its country, a city by name + region within its country (cities are unique per region — `city_unique_name_region_country`, so Kansas City MO and KS both exist; a same-named city needs the `region` column, and a row naming a region fills it in on a region-less match; new city slugs carry the region code, `kansas-city-ks-us`), a place by name within its city (ignoring capitals), and blank cells keep existing values. An event city not in the catalogue becomes a typed town. Imported rows are published (activity `source="import"`). The upload waits in the session between preview and confirm.
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
- **Lifecycle:** an *activity* is an undated idea ("Go to Oktoberfest") with an optional catalogue place (`country` / `region` / `city`; a city fills in the other two on save; `suggested_location` is free text for unlisted places, `place_name` renders either) and `recurrence` (anytime / yearly / seasonal / once) plus `usual_months`. A recurring activity has **one event per occurrence** (Oktoberfest 2026, Oktoberfest 2027), never one repeating event: each year has its own dates, prices, approval, bucket items and trips (`Event.is_recurring` is unused). On an event of a yearly activity, "Add <next year> dates" opens `/events/add/?copy=<pk>` with the dates moved a year on (or links next year's event if it exists); for a several-times-a-year (`seasonal`) activity such as a team's home games it is "Add another date" (`?copy=<pk>&another=1`: same details, date blank) — `events.views._next_date_link`. An activity may name a `venue` (a POI; fills in its city), events have `poi` as their venue (on `EventForm`, pre-filled from the activity), and the CSV import has activity `venue` / event `place` columns. The activity page's Dates card groups events by season (`Activity.dates_by_season` / `season_label`: when `usual_months` wraps New Year a January game belongs to the season that started the autumn before, "2026–27") with past dates folded away. The region/city selects are filtered by country in the browser by `locations/country_filter.js` + `apps.locations.widgets.CountryTaggedSelect` (also used by the city admin). An *event* is a dated occurrence of it (`Event.related_activity`, e.g. Oktoberfest 2027; `/events/?activity=<slug>` lists an activity's dates and `/events/add/?activity=<pk>` pre-fills one); a *trip* is the plan for going. Activities and events share ONE category list (`activities.ActivityCategory`; `EventCategory` was removed in events 0005/0006, which copied categories across by name). An event with no category takes its activity's. The activity page links to its dates via the shell partial `partials/_activity_dates_links.html` (`url … as`), so activities doesn't depend on events.
- **One look for activities and events:** detail pages use the shared `partials/_detail_header.html` (banner with picture or clay background, category, title, date/recurrence and place, approval badge with a one-line explanation) and the same layout (sections left; Quick Info and Actions cards right); list pages (`activity_list`, `my_activities`, `event_list`, `my_events`) use the shared `partials/_catalogue_card.html`. Change both through those partials. (`my_activities.html` used to be a symlink to `activity_list.html`; it is a real template now.)
- **Pictures:** activities and events have an optional `featured_media` (FK to `media_app.Media`, like places). Their forms use `apps.media_app.forms.PictureFormMixin` (`setup_picture()` in `__init__`, `save_picture(user)` after save; views pass `request.FILES`, templates use `enctype="multipart/form-data"` and `partials/_picture_field.html`): an upload becomes a `Media` row attached to the object, scaled to at most 2400 px (`apps.core.utils.images.shrink_image`), max 20 MB (nginx allows 25). A new event of an activity starts with the activity's picture (`Event.save()` on create, so the form, CSV import and admin all do it; the same `Media` row), and an event copied to next year keeps last year's picture instead; either is replaced for that event only by uploading one (or removed with "Remove the current picture"). **Shown picture:** templates use `display_media`, never `featured_media`, for activities and events: their own picture, else (events) the activity's, else the place's — venue, city, region, country (`PICTURE_PATHS`, walked by `apps.media_app.pictures.first_media`, images only). List views `select_related(*Model.PICTURE_RELATED)` so cards cost no extra query; edit forms still show only the object's own picture.
- `Event` uses `Approvable` too, plus `created_by`. Users submit events at `/events/add/` (staff publish directly); a submission is `pending` and visible only to its creator and staff (`Event.objects.visible_to(user)` / `event.is_visible_to(user)`, 404 otherwise) until approved in the "Events" approval queue (seeded by `events` migration 0003, with starter `EventCategory` rows). Creators can edit/delete until approval; editing a rejected or changes-requested event re-submits it.

### Users, roles and per-user settings
- Roles are Django Groups: `Vendors` and `Content Providers`. Users request a role through `accounts.RoleRequest`, and approving the request adds them to the group. Staff access uses the `accounts.can_access_staff_dashboard` permission. Check access with the `User` properties `is_vendor`, `can_access_staff` and `can_access_*_dashboard`.
- Per-user data is spread over `Profile`, `AccountSettings` (`user.settings`: units, currency, language, timezone, theme) and `TravelPreferences` (`user.travel_preferences`). `UserPreferences` is the older combined model and was split into these.
- Request-time plumbing:
  - `apps.core.middleware.UserTimezoneMiddleware` activates the user's timezone.
  - `UserThemeMiddleware` sets `request.theme` and the `ui_theme` cookie.
  - Context processors in `apps/core/context_processors.py` expose `user_units`, `user_currency`, `user_theme`, `user_travel_styles` and similar to every template.
  - `apps.rewards.context_processors.rewards_context` adds rewards data.
  - `apps/core/templatetags/conversion_tags.py` provides unit and currency filters that use these values (`{% load conversion_tags %}` — tag libraries load by name, not path).

### Templates and styling
- Site-level templates are in `templates/`: `base.html` (Tailwind app shell with header, sidebar and messages), `base_marketing.html` (public pages), `partials/` and `components/`. App templates extend `base.html`. Reusable pieces are included with `{% include 'components/cards/stat_card.html' with color="clay" ... %}`; see `templates/components/README.md`.
- App templates live in `apps/<name>/templates/<name>/` and are still referenced as `"<name>/…html"` (e.g. `trips/trip_detail.html`); the `apps/` directory never appears in a template name.
- Detail and list views pass `breadcrumb_list` (built with `apps.core.utils.breadcrumbs`); templates fill `{% block breadcrumbs %}{% include "partials/_breadcrumbs.html" with breadcrumbs=breadcrumb_list %}{% endblock %}`, which `base.html` renders above the messages. Paginated lists use `{% include "partials/_pagination.html" %}` (needs `page_obj`; `{% querystring %}` keeps the filters).
- **Bootstrap is not loaded.** `base.html` dropped Bootstrap's CSS/JS in `ddd00d7`; any template still using its classes (`row`/`col-*`, `btn`, `card`, `list-group`, `badge bg-*`, `form-control`, `data-bs-*`) renders unstyled. Convert to Tailwind plus the shared `sbl-*` components in `styles.css` (`sbl-card`, `sbl-btn` + `-primary`/`-secondary`/`-accent`/`-danger`/`-outline`, `sbl-input`, `sbl-label`, `sbl-badge-*`, `sbl-alert-*`, `sbl-list`, `sbl-table`, `sbl-page-title`). Interactive bits use Alpine.js (loaded in `base.html`). All live templates are converted (site shell, `pages`, `locations`, `accounts`, `rewards`, `activities`); form widgets set `sbl-input` / `sbl-check` in `forms.py`. The unused Bootstrap-era templates were deleted.
- Tailwind source is `theme/static_src/src/styles.css`, using Tailwind v4 (`@import "tailwindcss"`) with the forms and typography plugins. DaisyUI is in `package.json` but not loaded (no `@plugin`). `@source` globs cover `templates/` and `apps/*/templates/`; the brand palette is a `@theme` block (`earth-*`, `warm-*`, and `accent-*` = clay, which the trips components use). `tailwind.config.js` is ignored by v4. The old hand-written `!important` utility block is gone (it overrode every `hover:`/responsive variant); don't add `!important` utilities back. The built `theme/static/css/dist/styles.css` is committed: rebuild with `python manage.py tailwind build` (dev only) after template or CSS changes. `base.html` / `base_marketing.html` link it with `{% static 'css/dist/styles.css' %}` (not django-tailwind's `{% tailwind_css %}` tag, so production needs no tailwind app); in DEBUG a `?v=` from the `site_branding` context processor defeats browser caching.
- **Trips pages are scoped.** Every trips template extends `trips/base_trips.html`, which sets `content_class` = `trips-ui` (and a default `wrap_class` width) on `base.html`'s content area. The itinerary component layer (`.card`, `.btn`, `.badge-*`, `.callout-*`, `.chip`, form controls) and its `@media print` rules are written as `.trips-ui …` in `styles.css`, so they never restyle other apps' templates. Tests assert those class names. Site header, sidebars and footer carry `print:hidden`.
- Icons: Bootstrap Icons (`bi bi-*`) and flag-icons, both loaded from a CDN.
- **Bucket lists (`apps/bucketlists`):** a `BucketListItem` is the user's thread through the lifecycle, `item.stage` = idea → dated → trip → done. Its "what" is one of: an `activity`, a `city`, an `event` on its own, one or more `pois` (M2M; adding a POI makes it "an activity for them", with an optional `custom_title` as the goal's name), or a custom goal (`custom_title`); `item.kind`, `item.target`, `item.target_url` resolve it. An activity item is dated by picking one of that activity's events (`item.event`, must be `related_activity` of it); other items are dated by `target_date`/`target_end_date`. Adding an event whose activity is already on the list dates that item instead of starting a new one. "Plan a trip" (`bucketlists:plan_trip`) is open to any signed-in user, pre-fills from `item.dates`/`item.place`, creates the `Trip` with an editor grant and sets `item.trip` (the FK lives on the item, so `bucketlists` → `trips`, never the reverse); `item.live_trip` ignores soft-deleted trips. **Several goals can share one trip** (`item.trip` is a plain FK): "Plan a trip" also lists the user's current trips (overlapping dates first) to add the goal to (`bucketlists:add_to_trip`); the trip page links (shell partial `partials/_trip_goals_link.html`, no query) to `bucketlists:trip_goals`, which lists the user's goals on that trip and lets them add or remove others; `bucketlists:remove_from_trip` unlinks. Seeing the trip is enough (a traveller can attach their own goal to a family trip); it changes the goal, never the trip. Migrations 0003–0005 are hand-written (schema / data / drop `poi`) because Postgres refuses index creation after a data change in the same transaction. Items are private to their owner (other users get 404) and `is_public` defaults to False; `/bucketlists/u/<username>/` shows public items only when the owner's `profile_visibility` is `public`. Categories are per user (`item.categories`, through `BucketListItemCategory`). The "Add to bucket list" button is the shell partial `partials/_bucket_add_button.html` (`{% include … with kind="city" obj=city %}`); it uses `{% url … as %}` so catalogue apps render fine without bucketlists — keep lower-layer templates referencing it only that way. `signals.py` keeps `Activity/Event.bucket_list_count` recounted on every save and delete (old and new target, since an item can gain an activity or event after creation). **My dates** (`bucketlists:dates`, sidebar stage 3) lists the user's open goals by `item.dates`: coming up (with Plan a trip), needs a date (activity goals offer that activity's next 3 visible events, picked via `bucketlists:pick_date`), and date has passed. The sidebar (`partials/_sidebar.html`) is grouped by the lifecycle: Discover (activities, events, places) → Dream (bucket list) → Pick a date (My dates) → Plan (trips) → Done (bucket list `?status=completed`); events/activities a user *submitted* are under "My contributions" in the header user menu. Each numbered sidebar section folds (Alpine): the current page's section is always open, the others remember open/closed in `localStorage` (`sbl-nav-<name>`), open by default; Home and About never fold. "Add a goal" suggests catalogue matches as the title is typed (`bucketlists:suggest`, JSON: public activities, upcoming visible events, approved cities/POIs), and a custom goal's edit page can link it to one (`bucketlists:link_item`): status, dates, notes and categories stay, `custom_description` is appended to `personal_notes`, `custom_title` is cleared except for POI goals, and a target already on the list is refused.
- **Public pages stay honest:** the home page's stats are real published-catalogue counts (`pages.views._catalogue_counts`, cached an hour); no invented numbers, testimonials or features. Every footer link must resolve (`test_site_pages` walks them). `pages:contact` emails `LEGAL_CONTACT_EMAIL` with Reply-To the sender (honeypot field, 3 per session per hour, disabled while the address is a placeholder); `pages:help` explains the lifecycle.
- **Notifications:** `apps.notifications.services.notify(user, kind, title, message, url, obj)` creates a `Notification` and emails it unless `user.settings.email_notifications` is off or the address is a placeholder (mail errors are logged, never raised); `notify_staff(...)` reaches everyone with `can_access_staff`. Kinds (seeded by notifications 0002): `submission_reviewed` (from `Approvable.approve/reject/request_changes` → `_send_approval_notification`, to the submitter/creator, gated by `ApprovalSettings.notify_on_approval/notify_on_rejection`), `submission_received` (staff, from `Approvable.submit_for_review`, gated by `notify_on_submission`; the activity forms now call `submit_for_review` instead of setting PENDING by hand), `role_request_decided` (accounts sends the `accounts.signals.role_request_decided` signal; `notifications/receivers.py` reacts, because accounts may not import notifications), `trip_access_granted` (`trips/signals.py`, on a new `TripGrant` not granted to oneself). The header bell loads `notifications:unread_count` (JSON) after the page, so pages pay no query; `/notifications/` lists them, opening one marks it read. Cross-app notification tests live in `apps/pages/tests/test_notifications_flow.py` (pages may import everything).
- **Visitor counts:** `visitor_count` on POI, City, Region (locations 0011) and Country = distinct members who ticked off a goal there or travelled (with an account) on a finished trip naming the city (`Trip.cities` / `Day.city`); regions/countries roll up their cities. `apps/bucketlists/visitors.recount()` recomputes everything (bucketlists may read trips; locations may not); `bucketlists/signals.py` queues one recount per transaction (on commit) when a completed goal or a finished trip changes, and `manage.py recount_visitors` runs nightly on production (James's crontab) because trips finish by date. Pages show "Members who've been" only when non-zero; top attractions / a city's places sort by it.
- **Place types:** a POI's type is a `locations.PlaceType` row managed in the admin (Locations → Place types; locations 0012 seeded the 14 old `POI_TYPES`), deliberately separate from activity/event categories (a type is what a place *is*). `POI.poi_type` is a FK on `PlaceType.code` stored in the original `poi_type` column (locations 0013), so set it with `poi_type_id="sports"`; the code is read-only once saved, a type in use can't be deleted (PROTECT), and unticking Active retires it from choices while its places keep it (`forms.active_place_types`, `PlaceType.choices()`). The CSV `type` column takes a code or a name; export writes the name.
- **Pictures first:** the location lists (countries, regions, cities, places) and the regions/cities/places on a detail page sort the ones with a picture first, then their usual order (`locations.views.pictures_first`). Dropdowns, forms and "recently added" stay as they were.
- **Maps:** every map is `templates/partials/_map.html` (`with data_url=… height=… route=True`) fed by a GeoJSON view of ours and drawn by `apps/core/static/core/map.js` through the adapter named by `settings.MAP_PROVIDER` (`osm` = Leaflet 1.9.4 + markercluster from cdnjs with SRI, OpenStreetMap tiles; `MAP_TILE_URL` / `MAP_ATTRIBUTION`; `GOOGLE_MAPS_API_KEY` reserved). Never call a provider's API from a page: a new provider is one more adapter (`create`/`group`/`addPoints`/`addLegs`/`addRoute`/`toggle`/`fit`) in `map.js`. Popups are built with DOM methods (names are user-submitted). OSM tiles need a Referer: the site sends `Referrer-Policy: same-origin`, so the tile layer sets `referrerPolicy: "strict-origin-when-cross-origin"` (origin only); without it OpenStreetMap shows "Access blocked" tiles. Places map: `locations:poi_map` / `poi_map_data` (published places, same Search/Country/Type filters as the list via `views._place_filters`; List/Map switch `locations/partials/_list_map_switch.html`). Trip map: `trips:trip_map` / `trip_map_data` (`Day.city` = where you spend the day (Munich on Oktoberfest day even when staying in Augsburg; where you sleep is the stay): days' cities in date order, consecutive repeats merged, numbered; transport legs with both `origin_city` and `destination_city` (trips 0018; choices = the trip's cities, else all) drawn as lines styled by mode — flights arc, trains solid, road dashed — via the adapter's `addLegs`; without mapped legs the stops are joined by a plain line; leg cities and other `Trip.cities` are plain pins; never public; separate page so the detail query pin holds). A travel day (Augsburg → Munich → Manchester → Liverpool) is the main place you end up on the day plus one leg per hop. The trip map has switches (Cities / Places of interest / Travel legs): features carry `properties.layer`, the partial takes `extra_urls` (more GeoJSON merged in) and `controls` (id of the element with `<input data-layer=…>` switches), and the adapter draws each layer into its own `group()` that `toggle()` shows or hides. Places of interest come from `bucketlists:trip_map_places` (the viewer's *own* goals linked to the trip: goal POIs, activity venue, event venue; approved only), linked from the trip template with `{% url … as %}` so trips doesn't depend on bucketlists. **Stays** are `trips.Lodging` (a private booking, never a POI) with an optional `city` and `latitude`/`longitude` (trips 0019): `Lodging.locate()` fills the coordinates from the address via `apps/core/geocoding.geocode` (OpenStreetMap Nominatim, `GEOCODER_URL`, one request per save, identifying User-Agent; `GEOCODING_ENABLED`, off under `manage.py test`) — called by the stay forms (`LocatingStayMixin`: trip edit formset and admin), never on a plain save, and not repeated for an address already tried (`geocoded_address`); hand-typed coordinates win. `manage.py geocode_stays [--trip] [--retry] [--fill-days]` backfills at one lookup a second. Saving a stay with a city through those forms also fills the city of the days it covers (check-in up to, not including, check-out) that have none (`Lodging.fill_day_cities`; never overwrites; adds the city to `Trip.cities`; the trip edit page says how many). A day's city is where you spend the day, so the stay fill is a best guess: a day trip is the destination on the day (set by hand) plus out-and-back legs from the stay's city; an overnight flight is a blank-city day plus the leg. The map's `stays` layer (house pin) shows name, city and dates only — never confirmation number, rate or notes — at the coordinates or else the city centre.
- **Editing places:** country, region, city and place (POI) pages end their right-hand column with the same Actions card (`locations/partials/_actions.html`: Edit, shown to staff or the item's submitter, and Back to the list) (`locations.views.can_edit`, passed to the detail templates as `can_edit`). Region/city/POI use ModelForms in `apps/locations/forms.py` (with `PictureFormMixin`; the city's region select follows its country) and the shared `locations/location_edit.html`; the country edit page is older and hand-written. Edits keep the slug and the approval status.
- **Reviews (`apps/reviews`):** members review published activities, events, cities and places (`apps/reviews/services.TARGETS`, kind → model / `Review` field / detail URL; a city is `Review.location`, a place `Review.poi` from reviews 0002), one per member per item, editable. Visible (`is_approved`) reviews set the item's stored `average_rating` / `review_count` (`services.recount`, from `reviews/signals.py`); the shared detail header and catalogue card show them as stars. The Reviews card is the shell partial `partials/_reviews.html` (`{% include … with kind="city" obj=city %}`, only on approved items), which loads `reviews:for_target` after the page, so catalogue apps never import reviews and pages pay no query. "Mark done" can share the goal's rating and notes as a review (`bucketlists` → `reviews` is allowed; never the reverse); `bucketlists/signals.py` marks a review "Been there" (`is_verified_visit`) when its author ticked that item off. Report (`reviews:report`) notifies staff (`review_reported`) and lists on the staff dashboard; 3 open reports hide a review until staff decide in the admin. The vendor/trip/site review types and the response/helpful models are unused.
- **Badges:** `apps/bucketlists/badges.py` defines them (code, title, icon, a counter and a target: goals added, ticked off, countries, events, trips, photos). `award_badges(user)` runs after every goal save (signal) and photo upload, records each new badge once as a `BucketListMilestone` (unique user + `code`, bucketlists 0006) and sends a `badge_earned` notification. `progress(user)` feeds the strip (`bucketlists/partials/_badges.html`) on the dashboard and My adventures; the public bucket list shows earned ones only. `manage.py award_badges` backfills silently (`--notify` to announce).
- **Recommendations:** `apps/recommendations/services.for_user(Goals)` scores public activities and upcoming events (new date for an undated goal > same category > same country > popular; one card per activity); `pages.views._goals` builds `Goals` from the user's bucket list because `recommendations` may not import `bucketlists`. The recommendation models are unused.
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
  No grant, no access. `accounts.UserRole` holds only `creator` ("may create trips", app-wide,
  granted by staff); creating a trip gives its creator an editor grant. Delete needs an editor
  grant *and* `created_by`; `restore` and `manage` (editing grants) are staff-only. (The itinerary
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
- **Status badge and completion:** `Trip.status` is a hand-set planning stage (Starting → Fleshing out → Confirming → Ready to go). The badge (`trips/partials/_status_badge.html`, `Trip.badge`) shows that stage, or **Completed** once `end_date` has passed (`Trip.is_completed`, derived from the dates, never stored); the trip list puts finished trips under "Past trips". Saving a trip as Ready to go with open booking tasks shows a warning (as the admin already did). A finished trip's page shows the shell partial `partials/_trip_bucket_prompt.html` (`url … as`, no query, so the query pin holds), which posts to `bucketlists:trip_done`: the user's goal linked to the trip goes to its "mark done" page, or one is created for an unlinked trip. Tests that use the fixed 2026 fixture dates pin today with `mock.patch("apps.trips.models.django_timezone.localdate", new=…)`.
- **Places:** `Trip.cities` (M2M to catalogue cities) and `Day.city` (limited in the day form to the trip's cities). "Plan a trip" / adding a goal fills `trip.cities` from `BucketListItem.catalogue_cities()` — only when the user may edit the trip. Recommendations count the countries of the user's upcoming trips. Cities are never in the public view. The free-text `destination` stays for display and the public title.
- **Budget:** `TripExpense` (who paid, `shared_with` travellers; empty = everyone on the trip). `trips:trip_budget` (`/trips/<pk>/budget/`, linked from the trip header) shows totals per currency (no conversion), each traveller's paid/share/balance and a settle-up (`apps/trips/budget.py`: cents, payer absorbs odd cents, largest debtor pays largest creditor). Anyone who can see the trip sees it; editors add/edit/remove costs. Never in the public view; a separate page so the detail page's query count is unaffected.
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
  run lists the hops. The parsers stay pure and still emit `logistics_table` sections. The section
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
  editors. `views._place_legs` does the grouping in Python from the existing `transport` /
  `days__sections` prefetch (`section.placed_legs`, `day.auto_legs`, `day.travel_total` "2 legs ·
  ~3 h 15 min") — no new queries. `stage` is derived ("planned" without times, "scheduled" with,
  "booked" once a confirmation covers it); `est_duration` holds the rough time (`logistics.rough_duration`
  parses "~45 min", "2.5 hrs", "1:15"); `order` sequences same-day legs without times. A `travel`
  section's payload is `{"intro"?, "columns"?, "rows"?}` — rows are reference rows only, never hops.
  Editing: `trips:leg_edit` (grouped Route / Schedule / Details / Placement / Return, `next`
  checked with `url_has_allowed_host_and_scheme`), `trips:leg_delete`, `trips:leg_quick_add` (a
  planned leg typed like a table row on a day, cities matched by name), `trips:day_add_travel`.
  The trip edit page's Transport formset stays the bulk view (with `est_duration`, without
  placement).
- **Round trips:** a leg on the trip edit page (`TransportLegForm`) has "Also add the return trip"
  plus the return's local departure/arrival; saving creates a second, independent leg with the ends,
  cities and zones swapped (return departs in the destination's zone, arrives in the origin's) and
  mode/operator/currency copied, but not service number, confirmations, cost or notes. The fields are
  added in `__init__` (`LocalLegTimeMixin` rebuilds `declared_fields`). The admin stays one-way.
- **Confirmations attach like comments** (trips 0026–0028): a `Confirmation` holds the booking's own
  details (number, provider, optional `label`, `url` manage-booking link, `booked_on`, `cost` + `currency`
  for the whole booking, notes, `travelers` — blank = everyone); what it covers is `ConfirmationLink`
  rows, each a generic link (content type + id) to one item of the same trip: a leg, a stay, a day's
  section (a tour, a timed entry) or a meal (`models.CONFIRMABLE`; `link()` checks the trip, once per
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
- **The view page is for reading; adding is on Edit trip.** The trip page has no add forms or "Add …"
  links (items keep their small Edit link). Edit trip has **Travel by day** (each day's legs with Edit,
  the add-a-leg form `partials/_leg_quick_add.html` with `next`, "Add a travel section", and the "Turn
  “A → B” table rows into legs" link) and **Bookings & confirmations** (`#bookings`: every leg and stay,
  plus sections and meals that have one, each with its chips and a Confirmations link; loose ones; "Add
  a loose confirmation"). The day page links each section and meal to its confirmations; the section
  page too.
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
  to tick them off — offered, never automatic. The trip edit formset has Leg/Stay pickers scoped to
  the trip.
- **The detail page** holds a fixed query count (22 here, 4 of them from this site's
  middleware/context processors; one is the trip's cities; two are the confirmations' links and
  travellers — fixed per page, not per item); `test_detail.QueryCountTests` pins it (it warms the
  content-type cache first, so the count doesn't depend on test order).
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
  `audit_public_leak`, `unescape_html`. Tests: `python manage.py test apps.trips` (about 12 minutes
  for the whole suite).

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
| 3. Catalog | `locations`, `activities`, `vendors`, `events` | layers 0–2; within the layer: `activities` → `locations`; `vendors` → `locations`; `events` → `locations`, `activities` |
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
4. Rewards: one membership model owned by `rewards`, keyed to `Traveler` (recommended)?
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
- Rewards consolidation (Decision 4); `TripExpense` reinstated on the new `Trip`; post-trip
  rating feeding `reviews`.
- ~~"Plan this" from a bucket-list item to a new trip~~ — done ("Plan a trip", branch `bucket-lifecycle`).
- Retire the itinerary repo and its systemd service; redirect `/public/<uuid>/` on the old
  host to this site so shared links keep working.

### Trip items and confirmations

Plan: `docs/plans/trip-items-and-confirmations.md` (one record per trip item, shown in the
trip-wide lists and on its day; confirmations attached to the items they confirm). Phases A–F,
one branch each, in order; "Ask James" decisions there must be answered before the phase that
needs them. Status: Phase A (legs evolve in place, shown once in each view) done on branch
`phase-a-legs-in-place`; Phase B (confirmations attached to items, Quick reference generated) done
on branch `phase-b-confirmations`; Phase C (convert logistics tables into linked legs, trip-wide)
done on branch `phase-c-convert-tables`; Phase D (new itineraries start as legs) done on branch
`phase-d-new-itineraries-as-legs`; Phase E (booking tasks point at what they're about) done on
branch `phase-e-booking-tasks`; Phase F (`Booking` for everything else you reserve) next.

### Rules carried over from the itinerary project

These bit that project once each; they apply here from Phase 1 on.

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
