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

The `tests.py` files are currently empty stubs.

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
