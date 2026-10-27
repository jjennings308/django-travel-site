# Plan: a flag picture for every country, and a monthly country check

Status: C1 done (2026-10-27, branch `c1-country-flags`); C2 done (2026-10-27, branch `c2-check-countries`). Decided by James 2026-10-27. Two phases, one branch each, in order: C1 (flags),
C2 (the monthly check). Read with `CLAUDE.md` → "Pictures", "Pictures first", "SEO basics" and "Currency choices".

## Why

James wants each country's picture to be its flag, replacing any photo a country has now. He also has a REST
Countries key (`RESTCOUNTRIES_API_KEY` in `.env` on dev and production) and wants a monthly report of where our
country rows differ from theirs (renamed countries, retired currencies such as ZWL → ZWG, new calling codes).

## Decisions (James and Claude, 2026-10-27)

1. **Flags come from flag-icons, not the API.** flag-icons 7.2.3 is already on every page (MIT licence, the same
   flags). REST Countries' terms don't cover copying their flag CDN's files, so we don't.
2. **The flag replaces a country's current picture.** The old `Media` row and its file are kept (not deleted), only
   no longer the country's picture; the command lists which countries changed.
3. **The monthly check only reports.** REST Countries' terms (section 5) forbid keeping their data for more than
   three days, so the check compares in memory, prints the differences and stores nothing — no table, no cache file,
   no notification text holding their values. James edits a country by hand (or by CSV import) if he agrees.
   Nothing from them is shown on the site, so no attribution is needed; if that ever changes, section 7 asks for a
   "REST Countries" credit with a link.
4. **No live calls from pages.** As today, pages never call an outside service.

## C1 — Flags as country pictures (branch `c1-country-flags`)

Done. As built: the PNGs are 9.4 MB (257 flags, 1200 × 900; flags of 256 colours or fewer saved as lossless palette
PNGs — a lossy palette would shrink it further, at some cost to flags with emblems); `Media.is_flag` (staff-side,
titled "Flag of …") is how templates tell a flag from a photo — the smallest way that also covers events and
activities falling back to a country's picture; the flag is stored with `default_storage` under `site/flags/` because
`Media`'s upload path needs an uploader; `COUNTRY_FLAGS_ENABLED` (off in tests) keeps test runs from writing flag
files into `uploads/`; the country edit page is the old hand-written one (pick from your images, no upload or remove),
so it gained **Use the flag** only; every country `import_countries` seeds has a PNG (no exceptions).

- **Images in the repo.** A dev-only script `scripts/build_flag_pngs.py` takes flag-icons 7.2.3's `flags/4x3/*.svg`
  (from npm: `npm pack flag-icons@7.2.3` in a scratch folder, never added to `package.json`) and renders each to a PNG
  1200 px wide (4:3) with `cairosvg` (dev only; add it to `requirements-dev.txt`, not `requirements.txt`). Output:
  `apps/locations/flags/<iso2>.png`, committed, with flag-icons' `LICENSE` copied beside them as
  `apps/locations/flags/LICENSE`. So production needs neither Node nor cairo. Check the folder's total size and
  report it in the PR (expect a few MB; run the PNGs through Pillow's `optimize=True`).
- **Model.** `Country.flag_media` (FK to `media_app.Media`, null, SET_NULL, `related_name="+"`) so templates can tell
  the flag from a photo. One migration in `locations`; check it with `sqlmigrate`.
- **`manage.py country_flags [--dry-run] [--country XX]`** (in `locations`, idempotent): for each country with a
  two-letter `iso_code` that has a PNG, make (or reuse, if `flag_media` is set and its file is still there) a `Media`
  image row — file copied into normal media storage, title "Flag of <name>", attached to the country, not
  user-generated, `uploaded_by` None, public — then set `flag_media` and `featured_media` to it. Prints: made N,
  already set N, replaced a photo for N (listing them), no PNG for N (listing the codes, e.g. `XK`). It doesn't go
  through `quota.check()` (staff-side catalogue data; `uploaded_by` None) and doesn't call `shrink_image` (already
  1200 px).
- **New countries get one too.** `import_countries`, the CSV import (countries) and the country add page call one
  helper, `locations.flags.attach(country)`, after saving a new country (only when it has no picture). Add
  `country_flags` to the seed order in CLAUDE.md, after `populate_flag_emojis`.
- **Showing a flag.** A flag is 4:3 and must never be cropped:
  - the country page's header banner, list cards and "pictures first" (`pictures_first` already counts it as a
    picture, so every country now sorts as having one — fine) show it with `object-contain` on the warm background
    when `country.featured_media_id == country.flag_media_id`, and as now (`object-cover`) for a photo;
  - the social share picture (`place_meta` / Open Graph) uses it;
  - events and activities fall back to the country's picture last (`PICTURE_PATHS`), so a card with no other
    picture now shows a flag; make that fallback `object-contain` too (the card partial can tell from
    `display_media`'s owner, or simply mark `Media` rows whose title starts "Flag of" — pick the smallest way and
    say which in the PR).
- **Editing.** The country edit page keeps "Remove the current picture" and upload: an upload replaces the flag as the
  picture (the flag `Media` stays, `flag_media` unchanged), and a **Use the flag** button sets `featured_media` back to
  `flag_media`.
- **Tests** (`apps/locations/tests/`, a new `tests/` package if the app has none yet): the command makes one `Media`
  per country, reuses it on a second run, replaces a photo and lists it, skips a code without a PNG; a new country
  from each of the three paths gets its flag; the header renders `object-contain` for a flag and `object-cover` for a
  photo; Use the flag; every committed PNG opens in Pillow at 1200 × 900 and every two-letter code in
  `import_countries`' data has one (list the exceptions). Page query counts unchanged.
- **Help:** the staff guide that covers seeding / the catalogue (`running-the-site`) gets a line on `country_flags`;
  bump its `updated`.
- **James runs it:** on dev, `country_flags --dry-run`, then for real and look at a few country pages; on production,
  `pg_dump` first, then `country_flags`.

## C2 — The monthly country check (branch `c2-check-countries`)

Done. As built: the API couldn't be called from Claude Code's session, so the client follows the published docs
(`data.objects` / `data.meta.more`, `response_fields`, pages of 100, Bearer header) and reads `currencies` — documented
only as "object" — either keyed by code or as a list of `{"code", "name"}`; check the first real run's output for an
unreadable shape. A name matches their common, official or an alternate name. "Theirs we don't have" (territories
mostly) is listed but doesn't make the exit 1, or every month would; ours they don't know does. A 404 for
`--country` reads as "not known".

- **Settings.** `RESTCOUNTRIES_API_KEY = os.environ.get("RESTCOUNTRIES_API_KEY", "")` in `config/settings/base.py`;
  `RESTCOUNTRIES_API_KEY=` (empty) in `.env.example` with a one-line comment. Empty in tests and CI. Never log it,
  never put it in a URL (use the `Authorization: Bearer …` header, not `?api-key=`), and keep it out of error emails
  (it's a setting, and `AlertEmailHandler` already sends no settings).
- **Client.** `apps/locations/restcountries.py`: `urllib.request` like `core/geocoding.py` (no `requests`), base
  `https://api.restcountries.com/countries/v5`, a timeout, an identifying User-Agent. Before writing it, look at a
  real response with the demo key `rc_live_demo` and fetch with the fewest requests the API allows (all countries in
  one call if it can; the free plan is 1,000 requests a month and 20 per 10 seconds — back off on 429, stop on 403
  with "monthly quota used up"). Map only what we compare; keep the response in memory only.
- **`manage.py check_countries [--country XX]`**: for each of our countries with an `iso_code`, compare `name`,
  `iso3_code`, `currency_code`, `currency_name`, `phone_code` and `continent` with theirs (normalise case, spaces and
  a leading "+" on calling codes; a country with several currencies matches when ours is one of them and the report
  says the others). Prints one line per difference ("ZW currency_code: ours ZWL, theirs ZWG"), then countries they
  have that we don't and ours they don't know; exit 0 when nothing differs, 1 when something does, 2 on an API error
  (missing key → a clear message, exit 2). Writes nothing to the database or disk.
- **Schedule.** James adds a monthly cron line on production, e.g. `17 6 1 * *` running `check_countries`; cron mails
  him the output (`MAILTO`). Document the line in `scripts/README.md` next to the other crons.
- **Tests** (no network: patch `urllib.request.urlopen` with a small hand-written response shaped like the real one —
  don't commit a copy of their data): differences found and printed, multi-currency case, calling-code
  normalisation, missing / extra countries, exit codes, 429 back-off, 403 and missing key, and that nothing is saved
  (`assertNumQueries` for writes / no files created).
- **Docs:** CLAUDE.md — a line under the seed commands for `country_flags` (C1) and one for `check_countries` (C2),
  plus this plan's status.

## Not changing

- `flag_emoji` and the flag-icons `fi fi-xx` spans stay where they are (lists, search, the city box).
- Regions, cities and places keep their own pictures.
