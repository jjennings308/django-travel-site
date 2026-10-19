# Plan: the next batch — beyond the family, Phase 4's loose ends, the catalogue, and ops

Status: R12–R21 done (2026-10-19); R22 next. Follows `site-roadmap.md` (R1–R11, complete), so the
phases continue at **R12**. Hand to Claude Code **one phase per branch/PR, in order**. Read with
`CLAUDE.md`. Each phase lists its **Ask James** decisions; stop and ask before the phase that needs
them. Every phase that changes something a user sees updates its Help guide in the same PR
(`apps/pages/help/`, bump `updated`).

## Order and why

| Phase | What | Why here |
|---|---|---|
| R12 | Faster tests and CI on GitHub | The suite takes ~11 minutes and runs only on this machine; every later phase pays that |
| R13 | Delete my account, download my data | The privacy page promises both; needed before strangers sign up |
| R14 | Open sign-up and trip creation, and a first-run welcome | Today a new account can't start a trip without staff granting "creator" |
| R15 | Abuse guards, storage limits, unsubscribe | Strangers bring spam, big uploads and email complaints |
| R16 | Launch readiness: legal, terms versions, staging site | Mostly James's checklist, plus the code that records which terms were accepted |
| R17 | Post-trip ratings feed reviews | Phase 4: a finished trip asks once and turns answers into catalogue reviews |
| R18 | Trip items linked to the catalogue | Phase 4: a meal or a day's plan points at a catalogue place or activity |
| R19 | One exchange-rate source; retire unused models | Phase 4 tidy-up; less code to carry into growth |
| R20 | One search for the catalogue | Activities, events and places from one box, with filters |
| R21 | What's on: events by month, and on place pages | Makes the catalogue worth browsing |
| R22 | SEO basics | Sitemap, robots, page descriptions, link previews, event markup |
| R23 | Performance and dependency upkeep | Big-trip timings, slow-query check, scheduled dependency updates |

## James's checklist (no code)

- **Before R14 (open sign-up):** decide who may sign up (anyone, or invite-only for now), and make sure
  outgoing mail is set up for strangers' inboxes (SPF / DKIM / DMARC for the sending domain at smtp2go).
- **Before R16:** fill every `LEGAL_*` value; have Terms and Privacy read by someone qualified; choose a
  staging hostname (e.g. `staging.sharebucketlist.com`) and add its DNS record.
- **Data fixes still open:** Europe's meal types; "Hof" → "Hbf".
- **Itinerary leftovers** (R11): drop the local `itinerary` database, archive the GitHub repo, copy the
  final dump to the backup machine.

---

## R12 — Faster tests and CI on GitHub

**Status: done** (2026-10-18, branch `r12-tests-ci`). Decision: CI on pushes to `main` only. The full
parallel suite went from 688 s to 70 s (test settings with MD5 hashing; R1's People tests were ~6 s each
from password hashing alone). The slowest tests left are the migration tests (≤ 20 s, run in parallel).

**Ask James:** run CI on GitHub Actions (free for this repo's size), and on every push or only on pull
requests? (Recommended: every push to a branch, plus `main`.)

- **Faster locally:** a `config/settings/test.py` (or test-only overrides) with the MD5 password hasher
  (account creation is most of many tests' time), in-memory email, and no `django-browser-reload`.
  Measure before/after per app; target under 5 minutes for the full parallel run.
- Find the slowest tests (`--timing`), and the migration tests that step the whole graph; share one
  stepped-back state where several tests need it.
- **CI:** `.github/workflows/test.yml` — Postgres service container, `pip install -r
  requirements-dev.txt`, `check_layers.py`, `makemigrations --check`, `manage.py check --deploy` with
  dummy production env, the full suite with `--parallel`, and a check that the committed Tailwind CSS
  is up to date (build and `git diff --exit-code`).
- A status badge isn't needed; a failing run emails James (GitHub's default).
- **Tests:** the settings module is used by CI and the runner; a deliberately broken migration fails CI
  (tried once, then removed).

## R13 — Delete my account, download my data

**Status: done** (2026-10-19, branch `r13-delete-export`). Decisions: shared trips stay with the others;
30-day grace period. Changes from the plan: the download streams at the click (no stored file, no
emailed link); four user FKs became SET_NULL so catalogue items, pictures, reviews and trip notes
survive. Also bumped the GitHub Actions (checkout v5, setup-python v6, setup-node v5). James: add
`purge_deleted_accounts` to the production crontab (daily) and approve the privacy page wording.

**Ask James:** (a) when someone deletes their account, what happens to trips they created that others
are on? (Recommended: the trip stays with its other editors — creatorship moves to the longest-standing
editor; a trip with no other people is deleted with the account.) (b) Delete at once, or after a 14-day
grace period they can cancel by signing in? (Recommended: 14 days.)

- **Download my data** (Settings): a zip of JSON files (account, profile, travel profile and loyalty
  programs, bucket list, reviews, notes and comments they wrote, trips they can see — as the booklet
  data, not other people's private profiles) plus their own uploaded photos and tickets. Built in the
  background (`manage.py` job or on request with a size cap), emailed as a link valid 7 days.
- **Delete my account** (Settings, with password): grace period per (b); then their personal data,
  uploads (private storage too), grants, invites and calendar tokens go; reviews and catalogue
  contributions stay, shown as "a former member"; trips per (a). `TripChange.actor` already nulls.
- Staff see pending deletions on the staff dashboard; nothing is ever restored from backups to
  resurrect a deleted account (privacy page says so).
- **Tests:** export contains only the person's own private data; deletion removes files from storage;
  trips with others keep working; grace-period cancel.
- **Help + privacy page:** how to export and delete.

## R14 — Open sign-up and trip creation, and a first-run welcome

**Status: done** (2026-10-19, branch `r14-open-signup`). Decisions: every verified account may create
trips (staff can block one); sign-up invite-only for now (`SIGNUP_MODE=invite`: a trip invite link or a
sign-up code from the admin; set `open` to open it); role requests moved to Settings. R13's privacy
wording approved by James on 2026-10-19.

**Ask James:** (a) may every verified account create trips? (Recommended: yes — drop the staff-granted
"creator" role as a requirement; keep it only as a way to *revoke* for abuse.) (b) Open sign-up to anyone,
or invite-only (an invite link from R1, or a sign-up code) for now? (c) Keep the "request vendor /
content-provider role" boxes on the sign-up form? (Recommended: move them to Settings.)

- `can_create_trip` per (a); **New trip** on the trip list for everyone who may.
- Sign-up per (b); sign-up form trimmed per (c); the verify-email page explains the next step.
- **First-run welcome** on the dashboard for a new account: three steps with ticks — add a goal, plan a
  trip (or start one), invite someone — each linking to its Help guide; dismissible.
- Empty states on Trips, Bucket list and My dates say what to do first.
- **Tests:** a new verified account can create a trip; revoked creators can't; the welcome shows once and
  hides when dismissed or done; invite-only mode refuses sign-up without a code.
- **Help:** getting-started guide rewritten for a newcomer.

## R15 — Abuse guards, storage limits, unsubscribe

**Status: done** (2026-10-19, branch `r15-abuse-guards`). Decisions: 1 GB per account; no CAPTCHA.
Reports reuse `admin_tools.ReportedContent` (so R19 keeps that model); places are never hidden
automatically. James: approve the privacy line about counting attempts per IP.

**Ask James:** per-account storage limit for photos and tickets (Recommended: 1 GB), and a CAPTCHA on
sign-up only if spam appears (Recommended: honeypot + rate limit first, no CAPTCHA).

- **Sign-up and login:** honeypot field, per-IP rate limits (sign-up, login, password reset, invite
  accept), and a lockout message that doesn't reveal whether an account exists.
- **Storage:** per-account total across photos, albums and tickets; a clear message at the limit; staff
  dashboard lists the largest users.
- **Email:** every notification and digest email gets a one-click unsubscribe (`List-Unsubscribe` +
  `List-Unsubscribe-Post`, a signed link that turns that kind of email off without signing in).
- **Reporting:** a Report link on activities, events and places (reviews already have one), into the
  staff dashboard; three reports hide a user-submitted item pending review, as for reviews.
- Staff can suspend an account (inactive + reason) from the staff dashboard, which also removes its
  pending submissions from public view.
- **Tests:** rate limits; storage limit; unsubscribe link works signed out and only for its kind;
  reports and suspension.

## R16 — Launch readiness: legal, terms versions, staging site

**Status: done** (2026-10-19, branch `r16-launch-ready`). Decisions: `staging.sharebucketlist.com`
(DNS added by James); nightly disguised copy. Additions: basic auth over staging, travel-document numbers
blanked in the copy, staging has its own cache folders. James: the server steps in
`deploy/staging/README.md`; existing accounts accept the terms once on their next visit.

**Ask James:** the staging hostname and whether staging shows production data (Recommended: a nightly
copy with emails rewritten to `+staging` placeholders and outgoing mail off).

- **Terms versions:** `TERMS_VERSION` / `PRIVACY_VERSION` in settings; sign-up records which version and
  when; a changed version asks signed-in people to accept again (one page, then on with their visit).
- The legal pages' draft banner is replaced by a small "last updated" line once `LEGAL_*` are set.
- **Staging:** `config/settings/staging.py` (prod-like, mail to the console log, a banner "Staging —
  not real"), a `deploy/staging/` systemd unit and nginx site, and a script that copies production into
  staging nightly with emails rewritten (reuses `scripts/lib/sbl_common.sh`). James runs the server
  steps.
- **Tests:** version change asks again; staging settings refuse to send mail.

## R17 — Post-trip ratings feed reviews

**Status: done** (2026-10-19, branch `r17-trip-ratings`). Decision: ask everyone with access ("Been
there" only for roster travellers). Built in `reviews` (the layer table allows reviews → trips, not
the reverse, so the plan's "trips → reviews" was wrong); the daily digest run triggers it through a
`trips.signals.daily_run` signal, so no new cron line.

**Ask James:** ask everyone on the trip, or only those with an account who travelled (on the roster)?
(Recommended: account holders on the roster.)

- The day after a trip ends, each traveller gets one notification: "How was it?" → a page listing the
  trip's catalogue places (stays' cities, activities' places, R18's linked meals and plans), each with
  stars and an optional sentence, plus "Skip".
- Answers become `reviews` (one per member per item, as today; "Been there" verified, like ticked-off
  goals). `trips` → `reviews` is allowed by the layer table.
- Shows on the trip page's Overview after the trip as "Your ratings" (private), with Edit.
- **Tests:** the prompt goes once; reviews created and verified; skipping sends nothing again; layer
  check clean.
- **Help:** reviews guide (or bucket-list guide) gets "Rating a trip".

## R18 — Trip items linked to the catalogue

**Status: done** (2026-10-19, branch `r18-catalogue-links`). Decisions: show "On trips · N" (count only)
on place and activity pages; all live trips count; shown from 2 trips; meal → place, section → place or
activity. Added: a **Food & drink** place type (locations 0015), for notable restaurants only — most meals
stay typed text.

**Ask James:** should catalogue pages show "on N trips" counts? (Recommended: yes, a count only — never
which trips or who.)

- `Meal.poi` (a catalogue place, e.g. the restaurant) and `Section.poi` / `Section.activity` (optional),
  edited on the day page; suggestions by name match when the trip's cities have a place of that name.
- The trip page and booklet show the catalogue name as a link (web) / plain text (booklet, snapshot
  updated); the catalogue item shows "On N trips" per the decision (counted nightly with
  `recount_visitors`, never a query per page).
- `import_itinerary` suggests links in its dry run; never links automatically.
- **Tests:** links limited to the trip's cities; counts private; query pin stated; booklet snapshot.

## R19 — One exchange-rate source; retire unused models

**Status: done** (2026-10-19, branch `r19-rates-cleanup`). Decisions: keep the `vendors` app (and so
`Review.vendor` and the vendor review type) for a future vendor feature; keep the Vendors role; keep the trip
review type. Removed (all empty on production, counted first): the five recommendation models, five
`admin_tools` models (`ReportedContent` stays), `ReviewResponse`, `ReviewHelpful` and the "site" review type.
The catalogue's currency conversion uses the stored ECB rates; `requests` and its four dependencies left
`requirements.txt`.

**Ask James:** remove the `vendors` app (models only — no pages, nothing uses it) or keep it for a
future vendor feature? (Recommended: remove; it can be rebuilt from git history.)

- `apps/core/utils/currency.py` (live exchangerate-api.com, used by the catalogue's price filters)
  switches to R10's stored ECB rates (`apps.core.rates`); no live API calls remain.
- Remove unused models after confirming they're empty on production (a read-only count first):
  `reviews` response/helpful models and the unused review types, the `recommendations` models
  (the recommendation *service* stays), `admin_tools` moderation models if unused, and `vendors` per the
  decision. Each removal is its own migration, reviewed with `sqlmigrate` before applying.
- CLAUDE.md, the layer table and `docs/architecture/` updated.
- **Tests:** price filters convert with stored rates; the suite passes with the apps/models gone.

## R20 — One search for the catalogue

**Status: done** (2026-10-19, branch `r20-search`). Decisions: everyone may search (box in both headers);
countries and regions included; accents ignored (`unaccent`). Extensions in core 0002.

- One search box (header and `/search/`) over published activities, events (upcoming by default),
  cities and places, using Postgres full-text search (`SearchVector` with weights: name > place >
  description), with filters (kind, country, month, category) and results grouped by kind.
- Typo tolerance with `pg_trgm` similarity for short queries (migration enables the extension).
- **Tests:** ranking, filters, unpublished items never found, query count fixed per page.
- **Help:** places-and-events guide gets "Searching".

## R21 — What's on: events by month, and on place pages

**Status: done** (2026-10-19, branch `r21-whats-on`). Decisions: nearby = within 50 km of a city; venue pages
show their events; a multi-day event shows on every day it runs; the .ics is for anyone who can see the
event. Also fixed: `UserTimezoneMiddleware` read the deprecated `UserPreferences`, so the Settings time zone
was ignored and everyone was UTC (James chose to fix it here). Found: place pages need a login (search and
What's on link to them) — for R22.

- `/events/calendar/<year>/<month>/`: a month grid (list on a phone) of upcoming visible events, with
  country and category filters, linking prev/next month.
- City, region and country pages get "What's on" (next events there and nearby) and "Things to do"
  (activities), both from one query each.
- Each event gets "Add to my calendar" (a single-event `.ics`, reusing R4's builder).
- **Tests:** month boundaries and time zones; pending events hidden; query counts.

## R22 — SEO basics

- `sitemap.xml` (published activities, events, places, help guides, public pages) and `robots.txt`
  disallowing `/trips/`, `/accounts/`, `/staff/`, `/admin/` and `/public/` (shared trip links are
  unguessable, and must not be indexed if one is ever posted somewhere).
- Each public page: `<meta name="description">`, a canonical link, Open Graph and Twitter-card tags
  (title, description, picture) so shared links preview well.
- Events carry schema.org `Event` JSON-LD (name, dates, place, image); activities and places carry
  `TouristAttraction` / `Place` where it fits.
- **Tests:** sitemap lists only published items; robots disallows the private areas; JSON-LD valid.

## R23 — Performance and dependency upkeep

- A management command that times the trip page, booklet and calendar feed on the biggest trip and
  prints query counts and timings; run before and after this phase.
- Postgres slow-query check on production (read-only `pg_stat_statements` if enabled, else the logs) and
  the indexes it suggests, each its own migration.
- Dependency updates: `pip-audit` in CI (R12), a monthly reminder or Dependabot for Python packages, and
  the pinned CDN scripts (Alpine is on `3.x.x` — pin an exact version with SRI, as Leaflet already is).
- **Tests:** CI runs `pip-audit`; the CDN tags carry `integrity`.

## Done means

Each phase: its tests, `check_layers.py` clean, full suite (`--keepdb --parallel --noinput`, and CI
from R12 on) green, booklet snapshot and query pins changed only by a stated amount, Help guide updated,
CLAUDE.md updated, and this file's status line updated.
