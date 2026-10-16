# Plan: the trip page as a web page — one home per fact, the booklet stays as it is

Status: U1–U6 done (2026-10-16, branches `u1-booklet-guard`, `u2-page-shell`, `u3-day-timeline`,
`u4-contacts-info`, `u5-edit-this-day`, `u6-decisions`); U7 planned. Decisions below were answered by James on 2026-10-16. Hand to
Claude Code **one phase per branch/PR, in order** (U1 → U7). Read with `CLAUDE.md` → "Trips" and
`docs/plans/trip-items-and-confirmations.md` (whose phases A–E and `TripActivity` are done and are
the foundation here).

## Why

The PDF booklet (`trips/pdf/booklet.html`, `apps/trips/pdf.py`) now does the printing, and James
likes it as it is. The web trip page (`trips/trip_detail.html`) no longer has to double as a print
layout, so it can be designed for the web: for planning at a desk *and* for use on a phone during the
trip. Today it repeats itself and buries the day you need:

- **Same record shown twice:** every leg in full in the trip-wide "Getting around" list *and* on its
  day; every confirmation as a chip on its item *and* as a full card in Quick reference; every booking
  task on its item *and* in "Still to book".
- **Missing where it's needed:** stays only at the top (a day never says where you sleep — the booklet
  does); contacts only at the bottom, tied to nothing.
- **Ordered by kind, not time:** a day lists legs, then sections, then activities, then food.
- **One very long page:** 17 days plus reference; mid-trip on a phone you scroll to find today.
- **Crowded header:** seven actions and four rows of chips before any content.
- **Same fact typed twice in the content** (Europe 2027 examples): Day 2's phase says "Train Frankfurt →
  Butzbach (~45 min, RE30)" (a leg), "Check in Hotel Hessischer Hof" (a stay), "Da Franco… Call ahead:
  06033 65147" (a meal + a contact); Day 7 describes the Nightwatchman in a phase *and* a table;
  "📅 Book: ICE seats", "📅 Book Ahead: Neuschwanstein", "⚠ CRITICAL: tent reservations" callouts repeat
  booking tasks; trip notes hold flight/hotel summaries (legs/stays), six Augsburg hotel options (an
  open decision) and two taxi phone numbers (contacts).

## The rules (every phase follows these)

1. **One home per fact on the web.** A fact is shown in full once, in its home; anywhere else it is a
   one-line link to that home.
   - *Things that happen on a day* — legs, activities, meals, the day's narrative sections — live on
     their **day**. A **stay** lives on its **check-in day** (full card); its other nights show a one-line
     "Sleeping at …", its last morning "Check out …".
   - *Reference things* — confirmations, contacts, info notes, booking tasks — live in **Reference**.
     They are **linked to specific items** (a leg, stay, activity, meal or section), and the items'
     days are where they surface. (A day itself is a link target only when nothing on that day fits.)
2. **The booklet repeats on purpose.** Paper can't link and is used offline, so the booklet prints a
   linked reference thing in full on each day it surfaces *and* in its reference section. Its layout is
   otherwise unchanged; a snapshot test (U1) guards it, and a phase changes it only where this plan says
   so, updating the snapshot deliberately.
3. **Derived, not typed.** Where you sleep, what's on a day, what needs attention, which days a contact
   matters on — all computed from items and links, never stored a second time.
4. **Suggest, never rewrite.** Content clean-up (U7) proposes changes on a review page; nothing changes
   until an editor ticks and confirms.
5. **No new per-item queries.** The page builds everything from one prefetch (`views._trip_page_queryset`)
   in Python. Each phase states its query-count change; `test_detail.QueryCountTests` is updated only by
   the amount stated.

## Decisions (James, 2026-10-16)

| # | Question | Answer |
|---|---|---|
| 1 | Page shape | One page, **collapsible days** |
| 2 | Inside a day | **Timeline first** (timed items), then narrative |
| 3 | Which day opens | **Today** during the trip; **Day 1** if the trip is in the future (none forced open after it ends) |
| 4 | Desk or phone | **Both** — design for the phone, make it comfortable on a desk |
| 5 | What reference things link to | **Specific items**, which then put them on specific days |
| 6 | Trip-level Info home (tickets rules, taxis, tent guide) | **Yes** |
| 7 | Open decisions (Augsburg hotel options) | **A real item**: a decision task with its options |
| 8 | Content clean-up review | **Build it** (suggestions only) |
| 9 | Confirmations index shows the numbers | **Yes** |
| 10 | Cities / travellers / goals to Overview; Share, Delete into a ⋯ menu | **Yes** |
| 11 | Editing | **"Edit this day"** on each day, and it's where you **add** things to that day |
| 12 | Booklet unchanged + linked reference on its days, snapshot-guarded; cleaned-up wording flows into it | **Yes to both** |

## Target page (web)

```
Bavaria · Liverpool · Windsor — Europe 2027            [Edit trip] [PDF] [⋯]
Sep 17 – Oct 3, 2027 · 16 nights · Confirming           Map · Budget · Photos
Overview · Days · Reference                              ← sticky jump bar

OVERVIEW
 Day  Date     Where       Sleeping              Travel                 Highlights
 1    Fri 17   —           ✈ overnight           ✈ PIT→ATL→FRA          
 4    Mon 20   Augsburg    Hotel Augusta (in)    🚆 2 legs · ~3¼ h      Fuggerei
 5    Tue 21   Munich      Hotel Augusta         🚆 2 legs              Oktoberfest   ⚠1
 Needs attention: 3 not booked · 5 to do · 1 decision →
 Travelling: James, Regan, Debbie, John, Sara, Henry · Cities … · Your goals on this trip →

DAYS                                                    [Expand all]
 ▸ Day 3 · Sun Sep 19 · Marburg
 ▾ Day 4 · Mon Sep 20 · Augsburg — Travel day          [Edit this day]
     Sleeping: Best Western Hotel Augusta · check in   ☎ +49 821 …   GCH7JS
     09:10  🚆 Butzbach → Frankfurt Hbf     RE30 · planned · ~45 min
     10:00  🚆 Frankfurt Hbf → Augsburg Hbf ICE · booked · GCH7JS
     Any time  🎟 Fuggerei entry             ticket · not booked
     ─ Morning — Check out and train south (narrative)
     ─ Afternoon — Light Augsburg stroll
     ⓘ Bayern Ticket rules   ☎ Taxi Augsburg eG
     Food ideas: …           Notes on this day (2)
 ▸ Day 5 · Tue Sep 21 · Munich — Oktoberfest

REFERENCE
 Confirmations   GCH7JS  Delta · PIT→ATL, ATL→FRA · Day 1   Manage booking ↗
 Contacts        Hard Days Night Hotel (front desk) ☎ … · Day 10–12
 Info            Bayern Ticket rules · Day 5
 To do           CRITICAL Oktoberfest tent reservation · Day 5 …
 Not booked yet  …
```

---

## U1 — Guard the booklet, share the day assembly

**Status: done** on branch `u1-booklet-guard` (no migrations; query count unchanged at 24). As built:
`apps/trips/itinerary.py` holds `place_legs` (moved unchanged from `views._place_legs`),
`travel_total` (its wording, now reusable) and `attach_stays` (moved from `pdf.booklet_context`).
The snapshot (`apps/trips/tests/snapshots/booklet.html`, 501 lines) was recorded *before* the move and
still matches after it. It captures the HTML the `trip_pdf` view hands WeasyPrint (`render_pdf`
mocked, "printed" date pinned) rather than a separate `booklet_html` helper, so the test goes through
the same path as a download.

Goal: make the web free to change without touching the booklet.

- **Snapshot test** `apps/trips/tests/test_booklet_snapshot.py`: build a fixture trip covering every
  item kind (overnight flight, planned + timed legs, a stay spanning days, activities, meals, each
  section type, confirmations, contacts, tasks), render the booklet **HTML** (template + `booklet_context`,
  not WeasyPrint) with today pinned, normalise whitespace, and compare to
  `apps/trips/tests/snapshots/booklet.html`. `UPDATE_SNAPSHOTS=1 python manage.py test …` rewrites it.
  Commit the snapshot.
- **Shared day assembly** `apps/trips/itinerary.py`: move the per-day derivations both outputs need
  (stay per night with check-in/check-out — now in `pdf.booklet_context` — legs per day, travel totals)
  into functions the web view and `pdf.py` both call. Pure functions over prefetched objects; no queries.
  The snapshot must not change.
- No visible web change. Query count unchanged.

## U2 — Page shell: header, Overview, collapsible days, Reference index

**Status: done** on branch `u2-page-shell` (no migrations; query count unchanged at 24; booklet
snapshot unchanged; tests `test_page_shell.py`). As built: each stay's existing card moved onto its
**check-in day** (`partials/_stay_card.html`) rather than disappearing until U3 (agreed with James).
Found while building: legs whose date is no day of the trip had the old trip-wide list as their only
home, so they're shown **in full to everyone** under "Journeys not on any day" in Overview (editors
also get a check-the-date note), not only as editors' links. Stays whose check-in is no day are shown there too. "Decisions"
in Needs attention waits for U6. The Overview helpers (`overview`, `open_day`, `MODE_ICONS`) live in
`itinerary.py`; `attach_stays` now returns the stays outside the days.

- **Header:** title, dates · nights · status badge; primary **Edit trip** and **Download PDF**; Map ·
  Budget · Photos as quiet links; a **⋯ menu** (Alpine) with Share / Stop sharing (and the public link
  when shared) and Delete. Cities, travellers, goals link and the bucket-list prompt move to Overview.
- **Sticky jump bar:** Overview · Days · Reference.
- **Overview** (`#overview`): one row per day — day/date, where (`day.city`), sleeping (from U1's stay
  per night; "✈ overnight" when an overnight leg spans the night), travel (mode icons + "2 legs · ~3¼ h",
  or "A → B" for one leg), up to two highlights (activity titles, else the day theme), a ⚠ count of that
  day's not-booked items/open tasks. Each row links to its day and opens it. Below: a **Needs attention**
  line (not booked · to do · decisions · stray legs · pending tables) linking into Reference; travellers,
  cities, goals.
- **Collapsible days:** each day is a `<details id="day-N">` (works without JS). Open by default:
  **today's day** if today (`django.utils.timezone.localdate()`) falls in the trip; **Day 1** if the trip
  is in the future; none after it ends. A small script opens the target `<details>` when the URL hash or
  an Overview link points at a day, and **Expand all / Collapse all** toggles every day. The collapsed
  summary line shows date, city, theme and a ⚠ count.
- **Removed from the page:** the trip-wide **Getting around** list and **Where we're staying** cards
  (their information now lives in Overview + on days; the trip map keeps the geographic view). The
  editors' stray-leg and pending-tables notices move into Needs attention.
- **Reference** (`#reference`): **Confirmations is the home of a confirmation** — one row each, grouped as
  today (`confirmation_groups`): the **number** (monospace, easy to read out), provider, what it covers
  ("PIT→ATL, ATL→FRA") with a link to the first item's day, travellers, Manage booking ↗, notes, editors'
  Edit. Items keep only a chip with the number, linking to `#confirmation-<pk>`. **To do** and **Not
  booked yet** stay (home of tasks), compact, each linking to its item. **Contacts** stay here (U4 links
  them to items).
- Web print styling: don't add any. The trip page offers the booklet for printing.
- Booklet unchanged (snapshot). Query count unchanged (everything comes from existing prefetches).
- **Tests:** default-open day for a past / current / future trip (pin today); hash link opens a closed
  day (template contains the hook); a leg renders once on the page; a confirmation's full card renders
  once and its item has a chip linking to it; ⋯ menu holds Share/Delete only for those allowed; viewers
  see no editor links.

## U3 — The day: stay line, timeline, narrative

**Status: done** on branch `u3-day-timeline` (migration `trips 0030_meal_reserved_time`, one nullable
column; query count unchanged at 24; tests `test_day_timeline.py`). As built: `itinerary.timeline`
sets `day.timeline`, `day.any_time` and `day.food_ideas`; the compact leg row is `_leg_row.html` with
`compact=True`. A travel section with no intro or reference rows shows nothing in the narrative (its
legs are in the timeline). Meal confirmations now link to `#meal-N`. The booklet's one change: the
Food row shows the reservation time — the snapshot diff was exactly that line ("7:30 PM").

- **Day header line:** "Sleeping: <stay> · check in" (full stay card here on the check-in day: address,
  nights, rate, chips, notes, open tasks), "Sleeping: <stay>" on middle nights (links to the check-in
  day's card), "Check out: <stay>" on the last morning; split-group roster as today.
- **Timeline** (top of the day): legs, activities and **reserved meals**, sorted by local time (legs by
  local departure, activities by `start_time`, meals by their new reservation time). Items with no time
  follow under **Any time**, legs first in their `order`. Each row: time, icon, title, the key detail
  (operator / provider / place), stage or "not booked", confirmation chips, linked reference (U4), and
  editors' Edit link. Legs use `_leg_row.html` (add a compact variant); activities and meals get matching
  `_activity_row.html` / `_meal_row.html`.
- **Narrative after the timeline:** phases, free text, choose-your-adventure, callouts, logistics tables,
  and `travel` sections' intro + reference rows (their placed legs are in the timeline now; placement
  stays for editing and grouping). **Food ideas**: meals without a reservation time, as now. Then the
  day's comments.
- **Model:** `Meal.reserved_time` (`TimeField`, null/blank, wall clock on the day like activities) —
  migration `trips 0030`; on the day edit page's meal formset; `import_itinerary` leaves it blank.
- **Booklet:** the Food row shows the reservation time when set (the one deliberate booklet change in
  this phase; update the snapshot).
- Query count unchanged.
- **Tests:** timeline order across kinds (a 9:00 activity before a 10:00 leg), untimed items under Any
  time with legs in `order`, check-in/middle/check-out lines, a reserved meal in the timeline and an
  unreserved one under Food ideas, non-UTC viewer sees leg local times unchanged (the `at_zone` rule).

## U4 — Reference things linked to items: contacts and Info

**Status: done** on branch `u4-contacts-info` (migration `trips 0031_contacts_info_links`: adds only;
query count 24 → 26 as planned; tests `test_item_links.py`). As built: `itinerary.attach_links` and
`itinerary.anchor` (moved from the view's `_item_anchor`); `partials/_refs.html` (web) and
`pdf/_refs.html` (booklet). The item block is `trips:item_links` (inline on the leg and activity
pages; stays, meals, sections and days reach it by links). A note linked to a whole day reads "Day 2 ·
whole day". The booklet snapshot now includes a contact on a stay, one on a leg and an info note on a
section and a day (all deliberate).

- **`TripInfo`** (new, trips): `trip`, `title`, `body` (text, paragraphs), `url` (optional), `order`;
  `db_table` set. The home for trip-wide know-how: Bayern Ticket rules, Augsburg taxis, the Oktoberfest
  tent guide, packing, currency.
- **`Contact`** gains `address` and `url` (both optional).
- **`ItemLink`** (new, trips): `trip`, source (`source_type`, `source_id` — a `Contact` or `TripInfo`),
  target (`target_type`, `target_id` — a leg, stay, activity, meal, section, or a day when nothing on it
  fits); unique per source+target; indexed both ways; `link()` checks both belong to the trip; source and
  target models get `GenericRelation`s that delete their links. Same shape and resolution approach as
  `ConfirmationLink` (keep confirmations as they are).
- **Where a linked thing shows** (web): on each target item, a compact line — "☎ Front desk +44 151 …"
  (`tel:` link; email `mailto:`) or "ⓘ Bayern Ticket rules" (a `<details>` that expands the body) — and
  in the day's **Good to know** strip when linked to a section or the day. A contact linked to a stay
  shows on the stay line of each night. **Reference → Contacts / Info** are the homes (full), each with
  "On: Day 5 · Augsburg → Munich" links.
- **Booklet:** print each linked contact/info in full on the days it surfaces (under the item, or a
  "Good to know" block at the end of the day) **and** in Reference (Contacts as now; a new Info section).
  Update the snapshot deliberately.
- **Editing:** item edit pages (leg, stay, activity, meal via the day page, section) get a **Contacts &
  info** block like `partials/_item_confirmations.html`: pick an existing one, create one, or unlink
  (never deletes). Contact and Info get their own edit pages (`trips:contact_edit`, `trips:info_edit`,
  `…_new`, `…_delete`) listing and ticking what they're linked to. Trip edit keeps a Contacts list with
  links to those pages.
- **Query count:** +2 (item links with content types; trip info). State it in the test.
- Never public; `audit_public_leak` also checks contact phone numbers/emails don't reach the public view.
- **Tests:** link checks the trip; a contact linked to a stay shows on every night's stay line, once in
  Reference; an info note linked to a leg shows under that leg and on its day in the booklet; unlinking
  never deletes; deleting an item removes its links; tel/mailto rendering; query count.

## U5 — Edit this day (and add from it)

**Status: done** on branch `u5-edit-this-day` (no migrations; query count unchanged at 26; booklet
unchanged; tests `test_edit_this_day.py`). As built: the day page's old separate Activities and
Sections lists are folded into "On this day" (`views._day_workshop`, `partials/_workshop_row.html`);
"Add to this day" holds the leg quick add (inline, Alpine), activity, meal (jumps to the meal form),
contact or note for the whole day, and section-by-type buttons. A confirmation, or a contact for one
item, is added from that item's row. Legs show their `order` (edited on the leg's page).

- Each day (editors) gets **Edit this day** → `trips:day_edit`, which becomes the day's workshop, with
  an **Add** menu for that day: leg (the quick add), activity, meal (with reservation time), section (by
  type), contact or info linked to one of the day's items, confirmation for an item.
- The page lists the day's legs (Edit, order), activities, meals, sections and their links in timeline
  order, with Edit / Confirmations / Contacts & info for each. Saves return to
  `trip_detail#day-N` with that day open.
- Edit trip keeps its bulk views (Travel by day, Bookings & confirmations); both routes edit the same
  records.
- **Tests:** add each kind from the day page lands on that day; return URL opens the day; viewers and
  commentors get 403 on the day page; `next` is checked with `url_has_allowed_host_and_scheme`.

## U6 — Decisions as tasks with options

**Status: done** on branch `u6-decisions` (migration `trips 0032_decisions`: adds only; query count
26 → 27 as planned; tests `test_decisions.py`). As built: options are edited on `trips:task_options`
(saving options there turns a task into a decision; the task row on Edit trip also has a Kind
field); "Add as a stay / activity" go through `trips:option_add`, which pre-fills Edit trip's blank
stay row or the day's new-activity page and saves nothing. The booklet's Still to book prints
"Decide: …" with ✓ / ○ options — the snapshot diff was exactly the new decision row.

- `BookingTask.kind` (`book` default, `decide`) and **`TaskOption`** (new): `task`, `title`, `detail`,
  `url`, `est_cost` + `currency`, `order`, `chosen` (at most one per task). Migration adds both.
- A decision shows in **To do** as "Decide: Augsburg accommodation" with its options (title, cost, link)
  and, once chosen, the choice; the item it's about (e.g. the Augsburg stay, once it exists) via the
  existing task item link. Choosing an option does not create anything; it offers "Add as a stay" /
  "Add as an activity" links pre-filled from the option.
- Booklet: Still to book shows decisions with their options (snapshot update).
- **Tests:** one chosen option per task; a decision with no item still lists; options order; query
  count (+1 for options, stated).

## U7 — Content clean-up review

A review page that suggests moving retyped facts to their homes. **Suggestions only**: nothing is
saved until an editor ticks and confirms; one transaction; dismissals are remembered.

- **Detector** `apps/trips/tidy.py` — pure (no Django), like `logistics.py`; takes plain data, returns
  suggestions with a stable key, a kind, a before/after preview and the proposed change:
  1. **Narrative line repeats an item** — a phase highlight or free-text line on a day naming that day's
     leg (A → B / "Train X → Y"), stay ("Check in/out <stay name>"), meal (its name) or activity (its
     title) → *remove the line* (or keep its extra words as the item's notes).
  2. **Callout repeats a task** — a callout whose text names an open task's item or matches its title
     ("📅 Book: ICE seats") → *delete the callout* (the task already shows on the item) or *keep and
     link*.
  3. **Phone number in text** — international or local numbers in narrative, meal `reservation_notes` or
     trip notes → *create a Contact* (name from the nearest item/heading) linked to that item, and remove
     the number from the text.
  4. **Trip notes that belong elsewhere** — paragraphs duplicating legs/stays (flight and hotel
     summaries) → *remove*; a numbered list of options with addresses/links → *a decision task with
     options* (U6); a contact block → *contacts* (3).
  5. **A table that describes an activity** — a logistics table whose title matches an activity's title
     (Nightwatchman) → *move its rows into an Info note linked to the activity* and drop the table.
  6. **Day-number slips** — "Day 3" written in Day 4's text → *flag only* (no automatic fix).
- **Page** `trips:trip_tidy` (`/trips/<pk>/tidy/`, editors): suggestions grouped by day, each with a
  checkbox, preview and "Not this" (dismissal stored as a small `TidyDismissal(trip, key)` row).
  Linked from Needs attention for editors when suggestions exist (computed on the tidy page only — the
  trip page shows a plain link, no detection cost).
- **Command** `manage.py tidy_trip --trip <pk> [--apply]`: dry run lists suggestions; `--apply` applies
  only kinds 1–2 with high confidence (exact name matches); never 3–6.
- The booklet's wording changes as content is tidied (agreed); its layout doesn't.
- **Tests:** each detector on Europe-style text (the examples in "Why"); dry run saves nothing; applying
  is atomic; a dismissed suggestion doesn't return; idempotent second run.

## Data to fix by hand (seen in Europe 2027, not code)

- Every meal is typed **Lunch** (Da Franco is dinner, the hotel breakfast is breakfast).
- Return leg "Munich **Hof** → Augsburg **Hof**" should be Hbf.
- Day text is off by one ("Day 3 is a travel day" sits on Day 4; "Day 4 of Oktoberfest" on Day 5).

## Done means

- On the web each leg, activity, meal and stay is shown in full once, on its day; confirmations,
  contacts, info and tasks once, in Reference; everything else is a one-line link.
- A day opens to a timeline you can read on a phone; today (or Day 1) is open on arrival.
- Contacts and info notes are linked to items and surface on the right days on the web and in the booklet.
- The booklet's layout is unchanged except the agreed additions, each a deliberate snapshot update.
- `check_layers.py` clean, full suite green, `audit_public_leak` 0, query pin changed only as stated.
- `CLAUDE.md` → Trips updated at the end of each phase; this file's status line updated.
