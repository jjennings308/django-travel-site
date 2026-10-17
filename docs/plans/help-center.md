# Plan: a Help center on the site, written as markdown guides

Status: planning only (2026-10-17). Hand to Claude Code **one phase per branch/PR, in order**
(H1 → H4). Read with `CLAUDE.md` (Templates and styling, Dependency layers, Testing).

## Why

The site has one help page (`pages:help`, `apps/pages/templates/pages/help.html`: "The five steps"
and "Questions") and one written guide that nobody on the site can see
(`docs/guides/adding-a-day.md`). Trip companions are about to use the new trip page, Edit this day,
confirmations, contacts and the booklet, and they will need short how-to pages. James wants to keep
writing guides as plain markdown in the repo, and have the site show them.

## The rules

1. **One guide = one markdown file** in the repo, with a short metadata header. Adding a guide is
   adding a file; no code change, no migration, no admin.
2. **The Help page becomes the index.** `/help/` keeps its URL and its five-step overview, and lists
   the guides below it, grouped by audience. Each guide has its own page at `/help/<slug>/`.
3. **Guides are trusted content** (written by James or Claude Code, reviewed, committed). They are
   not user-submitted, so no sanitising, but they never contain secrets, server names or anything
   from CLAUDE.md's deploy section.
4. **Audience controls visibility:** `everyone` and `editors` guides are public (anyone, signed in
   or not, can read how the site works); `staff` guides are shown only to `User.can_access_staff`
   and are a 404 for everyone else.
5. **Guides describe what the site does now.** Every UI word in a guide (button, link, heading,
   message) is checked against the template that renders it. A guide carries an `updated` date; a
   change to a feature updates its guide in the same PR (add this to CLAUDE.md).
6. **Layering holds:** guides live in and are served by `pages` (layer 5). Lower apps link to a
   guide only with `{% url 'pages:help_guide' 'slug' as help_url %}{% if help_url %}…{% endif %}`,
   the same "url … as" pattern as `_bucket_add_button.html`, so they still render without `pages`.

## Guide file format

Location: `apps/pages/help/` (inside the app that serves it, so the app lifts cleanly).
Filename = slug: `apps/pages/help/adding-a-day.md` → `/help/adding-a-day/`.

```markdown
title: How to add a day to your trip
summary: Add a day, fill in its details, then add legs, activities and meals to it.
audience: editors
section: Trips
order: 20
updated: 2026-10-16

# How to add a day to your trip
…body…
```

- Header = Python-Markdown `meta` extension lines (`key: value`), then a blank line. Required:
  `title`, `summary`, `audience` (`everyone` | `editors` | `staff`), `section`, `order` (int,
  ordering within a section), `updated` (ISO date). Unknown keys are an error in the test, not
  silently ignored.
- Sections, in this order on the index: **Getting started**, **Trips**, **Bookings & contacts**,
  **Bucket list**, **Places & events**, **Staff**.
- Body: normal markdown — headings, numbered steps, tables, bold UI words. Links to other guides
  as `[text](/help/other-slug/)`; links to site pages by path (`/trips/`) — never to a specific
  trip id.

## H1 — The machinery, and move the existing guide

- **Dependency:** add `Markdown` (Python-Markdown, pinned) to `requirements.txt`. Extensions:
  `meta`, `tables`, `fenced_code`, `toc` (heading ids so a guide section can be linked:
  `/help/reading-your-trip/#confirmations`), `sane_lists`.
- **Loader** `apps/pages/helpdocs.py` (not `help.py`, which would clash with the `help/` folder of
  `.md` files): `all_guides()` → list of `Guide`
  dataclasses (slug, title, summary, audience, section, order, updated, html, toc), parsed once
  and cached in memory (`functools.lru_cache`; cleared in tests; in DEBUG re-read when a file's
  mtime changes so edits show without a restart). `guide(slug)` → one or `None`.
  `visible_to(user)` filters out `staff` guides for non-staff.
- **Views/URLs** (in `pages`): `/help/` (`pages:help`, kept) renders the existing five steps and
  questions, then the guide index grouped by section (title + summary + "for trip editors" /
  "staff" tag); `/help/<slug>/` (`pages:help_guide`) renders one guide with a "Help" breadcrumb,
  an "On this page" list from `toc` when the guide has 3+ `##` headings, its `updated` date, and
  "Related guides" (same section). Unknown slug or a staff guide for a non-staff user → 404.
- **Template** `pages/help_guide.html`: extends `base_marketing.html` like the current help page;
  guide body inside a `prose` (Tailwind typography plugin, already loaded) wrapper with styles for
  tables and numbered steps. Readable on a phone: tables scroll sideways inside their own box.
- **Move** `docs/guides/adding-a-day.md` → `apps/pages/help/adding-a-day.md` with `git mv`, add its
  header (`audience: editors`, `section: Trips`), remove the empty `docs/guides/`.
- **Rebuild CSS** (`tailwind build`) and commit `styles.css` — `@source` already covers
  `apps/*/templates`; the guide HTML itself only uses `prose`, so no class in a `.md` file needs
  scanning.
- **Tests** (`apps/pages/tests/test_help.py`):
  - every file in `apps/pages/help/` parses, has every required key and no unknown key, a valid
    audience/section/date, and a unique slug;
  - `/help/` lists every public guide and no staff guide for an anonymous user; staff see the
    staff section;
  - each public guide returns 200 anonymously; a staff guide is 404 for anonymous and a normal
    user, 200 for staff; an unknown slug is 404;
  - **every link inside every guide resolves**: `/help/<slug>/` targets exist (and `#anchor`
    targets exist in that guide's `toc`); other site paths resolve with `django.urls.resolve`;
  - `test_site_pages` still passes (the footer Help link).

## H2 — The three guides people need first

Write, check against the templates, commit. Each is short: a one-line lead, numbered steps or a
table, a "Problems" table at the end. James reviews them in the PR.

| Slug | Audience | Section | Covers |
|---|---|---|---|
| `reading-your-trip` | everyone | Trips | The trip page: header, Overview (one row per day, Needs attention), folded Days (opens on today / Day 1), a day's stay line, timeline, Any time, write-up, Food ideas, Good to know; Reference (Confirmations with numbers, Contacts, Info, Still to book); Map / Budget / Photos; Download PDF and what's in the booklet. Use `##` headings so other pages can link to `#overview`, `#days`, `#reference`, `#booklet`. |
| `sharing-and-access` | everyone | Getting started | Viewer / commentor / editor: what each can do; how to ask for editor access; the public share link (what it shows and never shows: no confirmations, stays, transport, contacts); stopping sharing. Check against `TripRole` / `role_capabilities()` and `public.py`. |
| `bookings-and-confirmations` | editors | Bookings & contacts | Adding a confirmation number on an item; one number covering several legs; a leg's stages (planned → scheduled → booked); Still to book, Not booked yet, decisions with options and "Add as a stay / activity"; loose confirmations (insurance). |

## H3 — The rest of the guides

Same format and checks; one PR, or split if it grows.

| Slug | Audience | Section |
|---|---|---|
| `starting-a-trip` (create a trip, from scratch or a goal; travellers, cities, dates, stays) | editors | Getting started |
| `adding-a-day` (exists — re-check after H1) | editors | Trips |
| `travel-legs` (planned vs booked, rough time, exact times and zones, return trips, which day a leg lands on, travel sections) | editors | Trips |
| `contacts-and-info` (linking a contact or note to an item or a day; where it shows on the page and in the booklet) | editors | Bookings & contacts |
| `tidying-an-itinerary` (turning tables into legs; the clean-up suggestions page) | editors | Trips |
| `comments-and-notes` (notes on a day, section, task or trip) | everyone | Trips |
| `bucket-list` (goals, picking a date, Plan a trip, marking done, photos and albums, badges) | everyone | Bucket list |
| `places-and-events` (submitting a place, activity or event; pending approval; reviews) | everyone | Places & events |
| `running-the-site` (approval queue, granting trip access and the creator role, CSV import/export, recount commands; **no** server names, credentials or deploy steps) | staff | Staff |

## H4 — Help where people need it

- **Trip page:** a small "?" link (`aria-label="Help: …"`) beside the Overview, Days and Reference
  headings → `reading-your-trip#overview` / `#days` / `#reference`; beside "Download PDF" →
  `#booklet`. Using the "url … as" pattern (rule 6). No extra queries (`QueryCountTests` unchanged).
- **Edit pages:** "How this works" link at the top of Edit trip (`starting-a-trip`), the day page
  (`adding-a-day`), the leg page (`travel-legs`), the confirmations block
  (`bookings-and-confirmations`), the Contacts & info block (`contacts-and-info`) and the tidy page
  (`tidying-an-itinerary`).
- **Sidebar / header:** a "Help" link in the user menu (the footer link stays).
- **Booklet:** unchanged (no links in print; the snapshot test must still pass untouched).
- **Tests:** each help link on those pages resolves to an existing guide and anchor (reuse H1's
  link checker on the rendered HTML).

## CLAUDE.md additions (in H1)

- Under Templates and styling: the Help center — guides are `apps/pages/help/*.md` with a metadata
  header, served by `pages:help` / `pages:help_guide`, `staff` audience gated by
  `can_access_staff`, lower apps link with "url … as".
- A standing rule: **a change to a user-facing feature updates its guide in the same PR** and
  bumps `updated`; `test_help` fails on a broken guide link.

## Done means

- `/help/` lists the guides by section; each guide has its own readable page, phone-friendly.
- New guides are added by committing a markdown file.
- Staff guides are invisible to everyone else.
- Trip and edit pages link straight to the relevant guide section.
- `check_layers.py` clean, full suite green (`--keepdb --parallel --noinput`), booklet snapshot
  unchanged, `QueryCountTests` unchanged.
