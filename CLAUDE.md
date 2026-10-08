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

**Seed reference data** with the idempotent management commands in `apps/locations/management/commands/`. Run them in dependency order: `import_countries`, then `import_regions`, then `import_cities`, then `import_national_parks` / `import_sports_venues`, then `populate_flag_emojis`. Imported rows are marked approved automatically.

## Deploying (staging / production)

`config.settings.prod` refuses to start without a real `DJANGO_SECRET_KEY` (≥ 50 chars, not
`django-insecure…`) and `DJANGO_ALLOWED_HOSTS`. It assumes nginx terminates TLS and sets
`X-Forwarded-Proto` (`SECURE_PROXY_SSL_HEADER`), redirects to HTTPS, uses secure cookies, starts
HSTS low (`SECURE_HSTS_SECONDS`, default 3600) and logs to stderr (systemd journal).
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
(pull, requirements, `check --deploy`, `pg_dump` + migrate when migrations are pending,
`collectstatic --clear`, restart, live check). Production uses `ManifestStaticFilesStorage`:
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
- `config/urls.py` mounts each app under its own namespace (`pages:` for home/dashboard/about, `locations:`, `activities:`, `trips:`, `bucketlists:`, `events:`, `rewards:`, `staff:`) with `include("apps.<name>.urls")`. Use namespaced names with `reverse` and `{% url %}`. `apps.accounts.urls` (login, register and so on) is not namespaced. Staff-only views live in `apps/accounts/staff_urls.py` under `/staff/`.
- `AUTH_USER_MODEL = 'accounts.User'` (a label reference — no `apps.` prefix). Login accepts a username or an email (`apps.accounts.backends.EmailOrUsernameBackend`).
- Settings that hold **module paths** (`INSTALLED_APPS`, `MIDDLEWARE`, `TEMPLATES` context processors, `AUTHENTICATION_BACKENDS`, logging handlers) use `apps.<name>.…`. Settings that hold **labels** (`AUTH_USER_MODEL`, `"label.Model"` strings, permission strings like `"accounts.can_access_staff_dashboard"`) do not.

### Shared base models (`apps/core/models.py`)
App models are built from abstract mixins: `TimeStampedModel`, `UUIDModel`, `SlugMixin`, `SoftDeleteModel`, `PublishableModel`, `FeaturedContentMixin`. Generate slugs with `apps.core.utils.generate_unique_slug`. Other helpers under `apps/core/utils/` handle breadcrumbs, currency, imperial/metric conversion and age. `docs/architecture/` has Mermaid diagrams of the intended app-dependency direction and FK ownership. Check them before adding cross-app foreign keys.

### Approval / moderation (`approval_system`)
User-submitted content inherits the `apps.approval_system.models.Approvable` mixin. It adds `approval_status`, priority, submitted/reviewed-by fields and an `ApprovalLog` audit trail. Admin classes add `ApprovableAdminMixin`. When filtering for public visibility, use `approval_status=ApprovalStatus.APPROVED`.
- `locations` models (Country, Region, City, POI) still carry the old `ReviewableMixin` (`status` field) next to `Approvable`. A migration from the old system is in progress (see `apps/approval_system/MIGRATION_GUIDE.md`). New code should use the `Approvable` fields. Both mixins define `approve()` / `reject()` / `request_changes()` and `ReviewableMixin` comes first in the MRO, so its versions set the legacy `status` and then call `super()` to reach `Approvable` (which owns `approval_status` and `ApprovalLog`). Keep that `super()` call, or approvals silently stop moving locations out of the pending queue.
- `Activity` also uses `Approvable`. App-level docs are in `apps/approval_system/*.md` and `apps/accounts/docs/`.
- **Lifecycle:** an *activity* is an undated idea ("Go to Oktoberfest"); an *event* is a dated occurrence of it (`Event.related_activity`, e.g. Oktoberfest 2027; `/events/?activity=<slug>` lists an activity's dates and `/events/add/?activity=<pk>` pre-fills one); a *trip* is the plan for going. Activities and events share ONE category list (`activities.ActivityCategory`; `EventCategory` was removed in events 0005/0006, which copied categories across by name). An event with no category takes its activity's. The activity page links to its dates via the shell partial `partials/_activity_dates_links.html` (`url … as`), so activities doesn't depend on events.
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
- **Bucket lists (`apps/bucketlists`):** a `BucketListItem` is the user's thread through the lifecycle, `item.stage` = idea → dated → trip → done. Its "what" is one of: an `activity`, a `city`, an `event` on its own, one or more `pois` (M2M; adding a POI makes it "an activity for them", with an optional `custom_title` as the goal's name), or a custom goal (`custom_title`); `item.kind`, `item.target`, `item.target_url` resolve it. An activity item is dated by picking one of that activity's events (`item.event`, must be `related_activity` of it); other items are dated by `target_date`/`target_end_date`. Adding an event whose activity is already on the list dates that item instead of starting a new one. "Plan a trip" (`bucketlists:plan_trip`) is open to any signed-in user, pre-fills from `item.dates`/`item.place`, creates the `Trip` with an editor grant and sets `item.trip` (the FK lives on the item, so `bucketlists` → `trips`, never the reverse); `item.live_trip` ignores soft-deleted trips. Migrations 0003–0005 are hand-written (schema / data / drop `poi`) because Postgres refuses index creation after a data change in the same transaction. Items are private to their owner (other users get 404) and `is_public` defaults to False; `/bucketlists/u/<username>/` shows public items only when the owner's `profile_visibility` is `public`. Categories are per user (`item.categories`, through `BucketListItemCategory`). The "Add to bucket list" button is the shell partial `partials/_bucket_add_button.html` (`{% include … with kind="city" obj=city %}`); it uses `{% url … as %}` so catalogue apps render fine without bucketlists — keep lower-layer templates referencing it only that way. `signals.py` keeps `Activity/Event.bucket_list_count` recounted.
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
- **Leg times** are stored UTC with an IANA zone per endpoint; render with the model's
  `*_local_*` helpers or the `trip_time` filters (`|at_zone:`…), never `|date` after them.
- **The detail page is printed to PDF** and holds a fixed query count (19 here, 4 of them from this site's
  middleware/context processors); `test_detail.QueryCountTests`
  pins it.
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
| 3. Catalog | `locations`, `activities`, `vendors`, `events` | layers 0–2; within the layer: `vendors` → `locations`; `events` → `locations`, `activities` |
| 4. User content | `bucketlists`, `trips`, `reviews`, `recommendations` | layers 0–3; within the layer: `bucketlists`, `reviews` and `recommendations` → `trips` |
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
