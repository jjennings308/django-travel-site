# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ShareBucketList (`SITE_NAME` in settings): a Django 6 travel site for bucket lists, trips, activities and locations. It uses PostgreSQL and server-rendered templates styled with Tailwind via `django-tailwind`. The site is moving from Bootstrap to Tailwind, so `*_bs.html` templates and crispy-bootstrap5 are leftovers.

## Commands

The virtualenv is at `.venv/`. `manage.py` uses `config.settings.dev` by default. Production uses `DJANGO_SETTINGS_MODULE=config.settings.prod`.

```bash
source .venv/bin/activate
pip install -r requirements.txt        # requirement.txt (singular) is a fuller pip freeze

python manage.py runserver
python manage.py tailwind start         # Tailwind watcher (theme/static_src, npm run dev)
python manage.py tailwind build         # production CSS -> theme/static/css/dist/styles.css
python manage.py collectstatic          # -> staticfiles/ (committed to git)

python manage.py makemigrations <app> && python manage.py migrate
python manage.py test                   # all apps
python manage.py test locations         # one app
python manage.py test locations.tests.SomeTestCase.test_method   # single test
```

The `tests.py` files are currently empty stubs. That changes with the itinerary merge (see "Work plan"):
its `trips` test suite comes across, and new tests should follow its pattern — a `tests/` package per
app, Django's built-in runner, no pytest.

**Database:** Postgres runs in a Docker container named `postgres`. Connection settings come from `.env` (see `.env.example`), which `config/settings/base.py` loads with python-dotenv. To reset the database (it takes a backup to `~/db_backups` first):

```bash
set -a; source .env; set +a
./scripts/reset_db.sh [db_name] [db_user] [pg_container]
python manage.py migrate
```

**Seed reference data** with the idempotent management commands in `locations/management/commands/`. Run them in dependency order: `import_countries`, then `import_regions`, then `import_cities`, then `import_national_parks` / `import_sports_venues`, then `populate_flag_emojis`. Imported rows are marked approved automatically.

## Architecture

### Settings and URLs
- `config/settings/{base,dev,prod}.py`. `base.py` reads env vars. `dev.py` and `prod.py` override `DEBUG`, `ALLOWED_HOSTS`, `SITE_URL` and email.
- `config/urls.py` mounts each app under its own namespace (`core:`, `locations:`, `activities:`, `trips:`, `bucketlists:`, `events:`, `rewards:`, `staff:`). Use namespaced names with `reverse` and `{% url %}`. `accounts.urls` (login, register and so on) is not namespaced. Staff-only views live in `accounts/staff_urls.py` under `/staff/`.
- `AUTH_USER_MODEL = 'accounts.User'`. Login accepts a username or an email (`accounts.backends.EmailOrUsernameBackend`).

### Shared base models (`core/models.py`)
App models are built from abstract mixins: `TimeStampedModel`, `UUIDModel`, `SlugMixin`, `SoftDeleteModel`, `PublishableModel`, `FeaturedContentMixin`. Generate slugs with `core.utils.generate_unique_slug`. Other helpers under `core/utils/` handle breadcrumbs, currency, imperial/metric conversion and age. `docs/architecture/` has Mermaid diagrams of the intended app-dependency direction and FK ownership. Check them before adding cross-app foreign keys.

### Approval / moderation (`approval_system`)
User-submitted content inherits the `approval_system.models.Approvable` mixin. It adds `approval_status`, priority, submitted/reviewed-by fields and an `ApprovalLog` audit trail. Admin classes add `ApprovableAdminMixin`. When filtering for public visibility, use `approval_status=ApprovalStatus.APPROVED`.
- `locations` models (Country, Region, City, POI) still carry the old `ReviewableMixin` (`status` field) next to `Approvable`. A migration from the old system is in progress (see `approval_system/MIGRATION_GUIDE.md`). New code should use the `Approvable` fields.
- `Activity` also uses `Approvable`. App-level docs are in `approval_system/*.md` and `accounts/docs/`.

### Users, roles and per-user settings
- Roles are Django Groups: `Vendors` and `Content Providers`. Users request a role through `accounts.RoleRequest`, and approving the request adds them to the group. Staff access uses the `accounts.can_access_staff_dashboard` permission. Check access with the `User` properties `is_vendor`, `can_access_staff` and `can_access_*_dashboard`.
- Per-user data is spread over `Profile`, `AccountSettings` (`user.settings`: units, currency, language, timezone, theme) and `TravelPreferences` (`user.travel_preferences`). `UserPreferences` is the older combined model and was split into these.
- Request-time plumbing:
  - `core.middleware.UserTimezoneMiddleware` activates the user's timezone.
  - `UserThemeMiddleware` sets `request.theme` and the `ui_theme` cookie.
  - Context processors in `core/context_processors.py` expose `user_units`, `user_currency`, `user_theme`, `user_travel_styles` and similar to every template.
  - `rewards.context_processors.rewards_context` adds rewards data.
  - `core/templatetags/conversion_tags.py` provides unit and currency filters that use these values.

### Templates and styling
- Site-level templates are in `templates/`: `base.html` (Tailwind app shell with header, sidebar and messages), `base_marketing.html` (public pages), `partials/` and `components/`. App templates extend `base.html`. Reusable pieces are included with `{% include 'components/cards/stat_card.html' with color="clay" ... %}`; see `templates/components/README.md`.
- Detail and list views pass `breadcrumb_list` (built with `core.utils.breadcrumbs`) to `partials/_breadcrumbs.html`.
- Tailwind source is `theme/static_src/src/styles.css`, using Tailwind v4 (`@import "tailwindcss"`) with DaisyUI and the forms and typography plugins installed. The brand palette (`earth-*` clay/olive/ochre/sage and `warm-50..900`) is defined in `tailwind.config.js`. It is also hand-written as `!important` utility classes in `styles.css`, because v4 does not read the JS config unless it is loaded with `@config`. If you add a new brand-color utility, make sure it really reaches the built CSS.
- Icons: Bootstrap Icons (`bi bi-*`) and flag-icons, both loaded from a CDN.

## Dependency layers

The goal is that any app can be lifted into another project by taking it plus the layers below it.
What makes that possible is the direction of imports, not where the app sits on disk, so the apps
stay flat at the repo root.

**Imports only point down this list.** An app may import from its own layer only when the order
inside the layer allows it (listed left to right; a later app may import an earlier one).

| Layer | Apps | May import |
|---|---|---|
| 0. Base | `core` | nothing local — Django and third-party only |
| 1. Identity | `accounts` | `core` |
| 2. Platform services | `notifications`, `media_app`, `approval_system`, `rewards` | layers 0–1 (`approval_system` → `notifications` is allowed) |
| 3. Catalog | `locations`, `activities`, `vendors`, `events` | layers 0–2; within the layer: `vendors` → `locations`; `events` → `locations`, `activities` |
| 4. User content | `bucketlists`, `trips`, `reviews`, `recommendations` | layers 0–3; within the layer: `reviews` and `recommendations` → `trips` |
| 5. Site | `pages` (to be created), `admin_tools` | anything |

`theme` (django-tailwind) and `config` sit outside the ladder.

Rules that follow from this:

- **Never `from accounts.models import User` outside `accounts`.** Models use
  `settings.AUTH_USER_MODEL` in the FK; code uses `django.contrib.auth.get_user_model()`. An app that
  imports the concrete `User` can only ever run inside this project.
- **A cross-layer FK pointing up is a design error, not an import problem.** A string reference like
  `"trips.Trip"` hides the import but still makes the lower app's migrations depend on the higher one.
  If a lower model needs to know about a higher one, put the FK on the higher model, or use a
  `GenericForeignKey`, or a signal.
- **Pin `label` in every `apps.py`** (`name = "trips"`, `label = "trips"`). The label decides table
  names, content types and migration history; pinning it makes a later move data-neutral. Most
  models here already set `db_table` explicitly — keep doing that for new models.
- **Each app ships its own templates** under `<app>/templates/<app>/`; only the shell
  (`base.html`, `partials/`, `components/`) lives in the top-level `templates/`.
- Keep `docs/architecture/app_dependencies.md` in step with this table. It currently draws the
  arrows the other way round (`core --> accounts` meaning "is depended on by"); either is fine, but
  say which in the file.

### Checking it

Until `scripts/check_layers.py` exists (Phase 0.5), this prints each app's local imports:

```bash
APPS="core accounts locations activities vendors events media_app bucketlists trips reviews notifications recommendations admin_tools rewards approval_system pages"
for a in $APPS; do [ -d "$a" ] || continue
  deps=$(grep -rhoE "^\s*(from|import) ($(echo $APPS | tr ' ' '|'))\b" --include=*.py "$a" \
    | grep -v migrations | sed -E 's/^\s*(from|import) //' | sort -u | grep -vx "$a" | tr '\n' ' ')
  echo "$a -> $deps"; done
```

### Known violations (from a read of the public repo, commit `ddd00d7`, Feb 2026)

Re-run the check against the local tree first; the local code may be ahead of that snapshot.

- `core` → `accounts`, `trips`, `bucketlists`: all from `core/views.py` (the home/dashboard pages:
  `User`, `Profile`, `Trip`, `BucketListItem`). Fix: move those views, their URLs and templates
  into a new layer-5 `pages` app. After that, `core` imports nothing local.
- `accounts` → `locations`: only `accounts/forms.py`, which builds currency choices from
  `Country`. Fix: build the choices from a static ISO 4217 list in `core/utils/currency.py` (which
  already handles conversion), so `accounts` does not need the catalog at all. This also breaks the
  loop `accounts` → `locations` → `media_app` → `accounts`.
- Concrete `User` imports in ten files: `media_app/models.py`, `trips/models.py`,
  `locations/views.py`, `bucketlists/models.py`, `admin_tools/models.py`, `reviews/models.py`,
  `rewards/models.py`, `notifications/models.py`, `recommendations/models.py`, `core/views.py`.
  Switching a model FK from `User` to `settings.AUTH_USER_MODEL` produces **no** migration when
  `AUTH_USER_MODEL` already points at that model — run `makemigrations --check` to confirm.

## Work plan

Two pieces of work, in this order: tidy the dependency layers (Phase 0.5), then merge the
itinerary app into this project (Phases 1–4). Work on a branch; do one phase per branch/PR.

**Open decisions — stop and ask James before the step that depends on one:**

1. Does anything in this project's current `trips*` tables need keeping? (Decides whether
   Phase 1 is drop-and-replace or needs a data migration.)
2. Does this project have outside users or a production database? (Decides whether
   migration history can be reset in Phase 1.)
3. Trip access model: keep itinerary's global role ladder, or move the role onto `TripGrant`
   per trip (recommended, since this site has self-registration)? Phase 1 can lift the ladder
   across unchanged either way; the change is its own step.
4. Rewards: one membership model owned by `rewards`, keyed to `Traveler` (recommended)?
   Phase 4 only.

### Phase 0 — prep

- `pg_dump` both databases before anything else (this one's container, and `itinerary` on
  `localhost:5432` — command in the itinerary CLAUDE.md under "Database").
- Upgrade Django 6.0.1 → 6.1.x (itinerary is on 6.1.1); `manage.py check` clean.

### Phase 0.5 — dependency layers

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

**Phase 1 — replace `trips` (lift and shift).**

- Remove our `trips` app. What imports it today: `reviews/models.py` (FK; and
  `reviews/0001_initial` depends on `('trips', '0001_initial')`), `recommendations/models.py`,
  and the views that move to `pages` in Phase 0.5. Repoint them at the new `Trip`.
- Copy their `apps/trips` in as `trips/` (flat). Rewrite `apps.trips.` → `trips.` in imports
  **and** in serialized paths inside migrations (e.g. `apps.trips.models.validate_timezone_name`).
  Leave `to='trips.day'`-style references alone — they resolve by label.
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

- Create `accounts.User` rows for their six people and `admin` with the **same usernames**.
- `dumpdata trips accounts.userrole --natural-foreign --natural-primary` from itinerary,
  `loaddata` here. Natural keys carry `Comment.content_type` and user FKs by username.
- Do **not** rebuild from `.docx` with `import_itinerary` — that discards every admin edit made
  since the original import.
- Verify: row counts per table match, every trip detail page renders, the detail page stays at
  17 queries, `audit_public_leak` exits 0, existing `public_token` links resolve.

**Phase 3 — styling.**

- Port their component layer (`.card`, `.chip`, `.callout*`, `.badge-*`, …) and the
  `@media print` rules into `theme/static_src/src/styles.css`; map their `accent` tokens onto the
  earth palette. Their print output is the deliverable (trips are printed to PDF) — compare a
  printed trip before and after.
- Resolve the DaisyUI class collisions by prefixing one side. Their tests assert some class names
  (`callout-warning`, `badge-critical`), so a rename updates those tests too.
- Add the trips templates to the Tailwind `@source` globs; retire their standalone npm build and
  `static/css/app.css`.

**Phase 4 — integrate (incremental, each its own PR).**

- `Trip` destination and `Day` city as FKs to `locations.City` / `Country`;
  `audit_public_leak` must stay green.
- Optional links from `Meal` / `Section` to `activities`, `vendors`, POIs.
- Rewards consolidation (Decision 4); `TripExpense` reinstated on the new `Trip`; post-trip
  rating feeding `reviews`.
- "Plan this" from a bucket-list item to a new trip.
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
