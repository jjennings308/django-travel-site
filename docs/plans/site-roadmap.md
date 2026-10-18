# Plan: what the site still needs — sharing, safety nets, travelling with it

Status: R1, R2 done (2026-10-18); R3 next. Hand to Claude Code **one phase per branch/PR, in order**
(R1 → R11). Read with `CLAUDE.md`. Each phase lists its **Ask James** decisions; stop and ask
before the phase that needs them. Every phase that changes something a user sees updates its Help
guide in the same PR (`apps/pages/help/`, bump `updated`), per the Help center rule.

## Order and why

| Phase | What | Why now |
|---|---|---|
| — | **James's checklist** (below) | Things only James can do; no code |
| R1 | Editors invite people to a trip | Today only staff can grant access — James is the bottleneck for every companion |
| R2 | Production backups (off the server) | The nightly dev sync is not a backup |
| R3 | Error alerts and a health check | A 500 today is only noticed if someone tells James |
| R4 | Calendar feed for a trip | Cheap; puts the trip into everyone's phone calendar |
| R5 | Tickets and documents on bookings | Boarding passes and e-tickets next to their confirmation |
| R6 | The trip page offline on a phone | Trains and abroad without data |
| R7 | Change digest | Group trips stay in sync without re-reading everything |
| R8 | Change history | Who changed what; undo a mistake |
| R9 | Checklists (packing, documents, before you go) | Commonly asked for |
| R10 | Budget in one currency | Europe trip mixes EUR, GBP, USD |
| R11 | Phone pass + Phase 4 loose ends | Polish and retire the old itinerary site |

## James's checklist (no code)

- **Placeholder emails:** the staff dashboard lists accounts with `@noemail.invalid`; set each real
  address in the admin (Debbie, Henry, John, Regan, Sara as applicable). Until then they can't reset
  passwords or receive invites/notifications.
- **Legal details:** fill the `LEGAL_*` values in production `.env` (the draft banner goes away), and
  have Terms / Privacy read over before inviting anyone outside the family. R1, R5 and R7 add new
  kinds of data (invite emails, uploaded documents, digest emails) — `privacy.html` must mention
  them; each phase drafts the wording, James approves it.
- **Data fixes** still open from `docs/plans/trip-page-ux.md` (meal types, "Munich Hof", day-number
  slips in text) — or run the tidy page for the slips.

---

## R1 — Editors invite people to a trip

**Status: done** (2026-10-18, branch `r1-trip-invites`). Decisions: (a) every editor, up to their own
role, never the creator; (b) 14 days; accepting account's email need not match. People is linked
beside Map · Budget · Photos (so viewers find it too) rather than in the ⋯ menu. The privacy page
has a draft "Trip invitations" paragraph for James to approve.

**Ask James:** (a) May every editor invite and change roles, or only the trip's creator? (Recommended:
every editor, but only up to their own role, and nobody can demote or remove the creator.)
(b) Invite links expire after how long? (Recommended: 14 days.)

- **Model** `TripInvite` (trips): `trip`, `email` (lower-cased), `role` (`TripRole`), `token`
  (random, unique, URL-safe), `invited_by`, `created_at`, `expires_at`, `accepted_at`,
  `accepted_by` (user, null), `revoked_at`. One open invite per trip + email (partial unique index).
  `db_table` set.
- **Capability** `invite` added in `role_capabilities()` for editors (per decision a). Staff keep
  `manage`. Access rules unchanged otherwise (404 no grant, 403 refused).
- **People page** `trips:trip_people` (`/trips/<pk>/people/`, linked from the trip page's ⋯ menu and
  Edit trip): everyone with a grant (name, role, granted by/when), change role (dropdown) and Remove,
  open invites (email, role, sent, Resend / Cancel), and **Invite someone** (email + role).
  - An email that belongs to an existing account → the `TripGrant` is created at once and the
    existing `trip_access_granted` notification is sent. No invite row.
  - Otherwise → a `TripInvite` and an email with the link `/trips/invite/<token>/`.
- **Accepting** `trips:invite_accept`: signed out → login or register (the invite email pre-filled),
  then back; signed in → shows trip name, inviter and role, **Join trip** creates the grant (or raises
  a lower existing role; never lowers), marks the invite accepted, lands on the trip. Expired,
  revoked or used → a clear page, no grant. The token is single-use; the accepting account's email
  need not match (forwarded invites work) — **Ask James** if it must match.
- Rate limit: 20 invites per trip per day. Invites never reveal whether an email has an account.
- `Traveler` linking: on accept, link or create the user's `Traveler` (existing signal) and offer to
  add them to the trip's travellers.
- **Tests:** each role's view of the People page; can't grant above own role; creator can't be
  demoted/removed; existing-account path makes a grant + notification; invite email sent (locmem);
  accept signed-in / after registering / expired / revoked / reused; non-editors 403; no-grant 404.
- **Help:** update `sharing-and-access`; add an FAQ line "How do I add someone to my trip?".

## R2 — Production backups, off the server

**Status: done** (2026-10-18, branch `r2-prod-backups`), tested here against a stand-in production.
Decisions: backups on popsicletoes.us at `~/backups/sharebucketlist/`; no off-site copy for now.
James: run the set-up in `scripts/README.md` there (`backup_prod.sh --check` first), then the first
restore drill. Weekly = newest backup in each of the 8 most recent weeks that have one; monthly
likewise per month.

Code in the repo; the timer runs on a homelab machine (James installs it, like the dev sync).

- `scripts/backup_prod.sh`: over SSH (read-only, as `sync_dev_from_prod.sh` does) take
  `pg_dump -Fc` of production, verify it with `pg_restore --list`, store as
  `~/backups/sharebucketlist/db/YYYY-MM-DD.dump`; `rsync` production `uploads/` and
  `private_uploads/` into `~/backups/sharebucketlist/files/` (add/update, `--link-dest` dated
  snapshots). Retention: 14 daily, 8 weekly, 12 monthly. One log line per run; non-zero exit and a
  journal error on failure. Reuse the sync script's helpers rather than copying them.
- `deploy/backup/sbl-backup.service` + `.timer` (daily 02:30, `Persistent=true`), install steps in
  `scripts/README.md`.
- **Restore drill** documented: `scripts/restore_check.sh <dump>` restores into a throwaway
  container/database, runs `migrate --check` and counts rows of key tables; James runs it monthly.
- **Ask James:** which homelab machine holds the backups, and should a copy also go off-site
  (e.g. an encrypted copy to cloud storage)? Not built until answered.
- CLAUDE.md: replace "this is a dev convenience, not a production backup" with where backups live.

## R3 — Error alerts and a health check

- `ADMINS` from env (`DJANGO_ADMINS="James <james@…>"`, parsed in `base.py`; empty = off). Add
  Django's `AdminEmailHandler` to `prod.py` `LOGGING` for `django.request` (ERROR) next to the console
  handler; include the request path and user id, never request bodies (forms may hold passport or
  loyalty numbers).
- Simple flood guard: at most one email per distinct error (exception type + location) per hour
  (cache key), the rest only to the journal.
- `/healthz/` (in `core`): 200 `ok` when the database answers `SELECT 1` and the static manifest
  loads; 503 otherwise; no auth, no details in the body; excluded from analytics.
- `deploy.sh`'s live check also hits `/healthz/`.
- James points his homelab uptime monitor at `/healthz/` (no code).
- **Tests:** handler configured in prod settings; flood guard; health 200 and 503 (DB mocked).

## R4 — Calendar feed for a trip

**Ask James:** include confirmation numbers in the event descriptions? (Recommended: yes — the feed
is behind a private token per person; say so on the page.)

- `TripCalendarToken` (trips): `trip`, `user`, `token`, `created_at`, `revoked_at`; one live token per
  trip + user. Calendar apps can't log in, so the feed URL carries the token:
  `/trips/calendar/<token>.ics`. Revoking (or losing access to the trip) makes it 404.
- **Feed** (`icalendar` library, pinned): one event per leg (UTC times; title "🚆 Frankfurt Hbf →
  Augsburg Hbf", location = origin, description = operator, service number, confirmation numbers,
  link to the day), per timed activity and per reserved meal (**floating** local times — wall clock
  wherever the phone is, which is what a traveller wants; end = `end_time` or +1 h), planned legs
  and untimed activities as all-day events on their day. Stable `UID`s (`leg-<pk>@sharebucketlist`)
  so updates replace events. Option `?mine=1` → only items whose travellers include the viewer (blank
  travellers = everyone).
- **Page:** "Add to calendar" in the trip page's ⋯ menu → instructions for Google / Apple / Outlook
  (subscribe by URL), Copy link, Reset link.
- Never public; `audit_public_leak` unaffected (tokens aren't the public token).
- **Tests:** feed validates and parses; leg times in UTC; activity floating times; all-day planned
  legs; `mine` filter; revoked / no-grant token 404; one query budget for the feed (prefetch).
- **Help:** new guide `calendar-feed`.

## R5 — Tickets and documents on bookings

**Ask James:** size limit per file and per trip? (Recommended: 10 MB per file, 200 MB per trip.)

- `ConfirmationFile` (trips): `confirmation`, `file` (`private_storage`, path
  `trips/<trip>/<uuid>.<ext>`), `original_name`, `content_type`, `size`, `uploaded_by`,
  `uploaded_at`. PDF, PNG, JPEG, HEIC (→ JPEG via the existing pre-save conversion).
- Upload / remove on the confirmation's edit page and from the item's Confirmations block (editors);
  download through an access-checked view `trips:confirmation_file` (anyone who can see the trip;
  `Content-Disposition` with the original name; 404 otherwise). Files are never in `MEDIA_ROOT`.
- Reference → Confirmations row and the item's chip show a 📎 count linking to the files.
- Booklet: lists file names under the confirmation (no embedding); snapshot updated deliberately.
- Deleting a confirmation deletes its files (storage too). Never public; `trip_leak_finders` ignore.
- **Tests:** upload limits and types; access (viewer can download, outsider 404, commentor can't
  upload); storage path outside media; delete cleans storage; booklet snapshot.
- **Privacy:** `privacy.html` paragraph on uploaded travel documents (James approves).

## R6 — The trip page offline on a phone

- A small **service worker** (`core/static/core/sw.js`, registered from `base.html` only on trip
  pages) that caches the trip page HTML, the CSS/JS it uses and the booklet PDF **when the user opens
  them**; network-first, falling back to the cached copy with a banner "Offline — last updated
  <time>". No background sync, no editing offline.
- **Save for offline** button on the trip page (⋯ menu) pre-caches the trip page and its booklet.
- Cache is per URL and cleared on logout (service worker message) — shared devices must not keep a
  trip after sign-out. Never cache other users' pages, admin or edit pages.
- Web app manifest (name, icons) so the site can be added to the home screen.
- Static paths stay hashed (`ManifestStaticFilesStorage`): the worker reads the manifest, never
  hard-coded file names; `deploy.sh`'s week-long retention of old hashed files keeps cached pages
  working across a deploy.
- **Tests:** worker and manifest served with the right content types; registration only on trip
  pages; logout clears (JS unit test or a documented manual check list in the PR).
- **Help:** `reading-your-trip` gets an "Offline" section.

## R7 — Change digest

**Ask James:** daily digest only, or also an immediate email for urgent changes (a leg's time
changed within 7 days of travel)? (Recommended: daily, plus immediate for that one case.)

- `TripChange` (trips): `trip`, `actor`, `when`, `kind` (added / changed / removed), `item_type`,
  `item_id`, `summary` ("Changed Frankfurt → Augsburg: departs 10:00 → 10:30"). Written by signals
  on legs, stays, activities, meals, sections, confirmations, days (only real field changes; bulk
  imports write one summary line).
- `manage.py send_trip_digests` (daily cron, like `recount_visitors`): for each user with access to a
  trip that changed in the last 24 h (excluding their own changes) → one `notify()` per trip with the
  list, through the existing notifications (respects `email_notifications`). New kind
  `trip_changed` (notifications data migration).
- Per-user, per-trip mute ("Don't email me about this trip") on the trip page's ⋯ menu.
- **Tests:** change capture per model; own changes excluded; muted users skipped; digest groups by
  trip; no email when nothing changed.

## R8 — Change history

Builds on R7's `TripChange`.

- **History page** `trips:trip_history` (editors and viewers): newest first, filter by day / person /
  kind, each line linking to the item.
- **Undo** for the last change of an item (editors): store the previous field values in
  `TripChange.before` (JSON) and restore them; deletions keep a JSON snapshot so a removed leg,
  activity or meal can be restored (not days or whole trips — those stay admin-only).
- Retention: keep 180 days (cron prunes).
- **Tests:** undo restores fields; restoring a deleted item recreates it with its confirmation links;
  permissions.

## R9 — Checklists

- `Checklist` (trip, title, kind: packing / documents / before you go / other, order) and
  `ChecklistItem` (text, `per_person` bool, done-by: M2M travellers with timestamps, order).
  A per-person item shows a tick per traveller ("Passport — James ✓ Regan ✓ Debbie ☐").
- On the trip page: Reference → Checklists; ticking is open to anyone with `comment` capability
  (AJAX-free form posts; Alpine for instant feel).
- **Templates:** "Start from a template" — International trip (passports, adapters, cards, insurance),
  Rail trip, Road trip; templates are markdown files like the Help guides (`apps/trips/checklists/`).
- Booklet: Checklists in Reference as tick boxes (snapshot updated).
- Needs attention: "3 documents not ticked" within 14 days of departure.
- **Tests:** per-person ticks; permissions; template import; booklet snapshot.

## R10 — Budget in one currency

**Ask James:** source of rates — manual rates per trip (simplest, offline), or a daily fetch from a
free API (ECB reference rates)? (Recommended: ECB daily rates cached in the database, with a manual
override per trip.)

- `ExchangeRate` (core): date, base, quote, rate. Daily `manage.py fetch_rates` (cron) from the ECB
  XML feed; outbound HTTPS from production must be allowed.
- Budget page: "Show totals in [USD ▾]" converts each expense at the rate of its `spent_on` date
  (else latest), shows "≈" and the rate used; settle-up still per currency unless the user ticks
  "Settle in USD". Per-trip override rates (Trip edit).
- Confirmation `cost` and activity `est_cost` feed an "Estimated trip cost" line on the Overview
  (converted).
- **Tests:** conversion with dated rates; missing rate falls back and says so; override wins;
  settle-up unchanged without the tick.

## R11 — Phone pass, and Phase 4 loose ends

- **Phone pass:** at 390 px wide, walk through and fix: sign in; add a goal; Plan a trip; open the
  trip on today; open a confirmation; add a leg from Edit this day; add a confirmation number; the
  Help pages. Tap targets ≥ 44 px, no sideways scroll except inside tables, sticky jump bar not
  covering anchors. List what changed in the PR with before/after screenshots.
- **Rewards** (CLAUDE.md Decision 4): one membership model owned by `rewards`, keyed to `Traveler`;
  migrate `trips.RewardsMembership` data; private like travel-profile data. **Ask James** first.
- **Retire the itinerary site:** confirm nothing still writes to it; final `pg_dump` archived; nginx
  on the old host redirects `/public/<uuid>/` to this site's `/public/<uuid>/` (James runs the
  server steps); stop and disable its systemd service; archive the repo on GitHub.

## Done means

Each phase: its tests, `check_layers.py` clean, full suite (`--keepdb --parallel --noinput`) green,
booklet snapshot changed only where the phase says, `QueryCountTests` changed only by a stated
amount, Help guide updated, CLAUDE.md updated, and this file's status line updated.
