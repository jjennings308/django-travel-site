# Plan: day-first planning (one page to read and edit, options inside the day)

Status: P1 done (2026-10-26, branch `p1-cities`); P2 done (2026-10-26, branch `p2-item-panel`); P3 done (2026-10-26, branch `p3-quick-add`); P4 done (2026-10-26, branch `p4-option-groups`); P5 done (2026-10-27, branch `p5-split`). P6 done (2026-10-27, branch `p6-ideas`). Decisions answered by James 2026-10-26 (listed below). Phases P1–P7, one
branch each, in order. Read with `CLAUDE.md` → Trips (especially "The web trip page is laid out for the web",
"Edit this day", "Decisions are tasks with options", "Confirmations attach like comments", "Places", "Currency
choices") and → Bucket lists. Builds on the finished Edit by day plan (`docs/plans/edit-by-day.md`): its item pages
(stay, leg, activity, to-do), currency choices and catalogue fill-ins are reused here, not replaced.

## Why

The trip pages were shaped by the printed Word itinerary they came from: sections, tables, a big edit form, and
separate pages to read and to edit. The booklet now has its own template behind a snapshot test, so the web can
be built for planning:

- **The trip is a row of days; everything you plan is an item on a day** that grows from a rough idea to a booked,
  confirmed thing on one record.
- **One page to read and edit.** Editors change things where they read them; an item opens in a side panel.
- **Options live inside the day.** "Choose one" groups (a dinner, an afternoon, a whole day, a hotel) that
  travellers vote on, an editor picks or splits.
- **Ideas wait on a shelf** until they have a day, and connect back to people's bucket lists.
- **Cities take care of themselves**: found by typing, gathered from what's planned, laid out by a route builder.
- Trip-wide pages (bookings, to do, getting around, costs, map, calendar, booklet) are **views of the days**, never
  places to edit.

## Decisions (James, 2026-10-26)

1. **Split** is wanted: different travellers can take different options on the same day.
2. **Votes** on options and ideas: one 👍 per person, visible to everyone on the trip.
3. **The booklet prints undecided groups with their options** (and a split day as tracks with names).
4. **Ideas shelf** is per trip, shared, and links to bucket-list goals (below).
5. **Simplify the UI**; the printed layout no longer drives the web.
6. **Convert existing data** (decision tasks, choose-your-adventure sections, phases/callouts/free text) with a
   review step, like Tidy.
7. **Ideas show on the trip map** as faint pins.
8. Phase order as proposed, with cities first (P1).

Defaults chosen in planning (change by telling Claude Code before the phase):

- Anyone with the `comment` capability or above votes; **editors** pick, split, reopen and move ideas onto days.
- Picking never deletes: unchosen options fold into **Considered** and can be reopened.
- No-JavaScript still works: every panel is a real page (the existing item pages), the panel just loads it inline.

## The model in one picture

```
Bucket list goal (mine, someday)
   │ "Add to a trip" / Plan a trip
   ▼
TripIdea on the trip's Ideas shelf (ours, no day yet, votes)          ← also from catalogue "Add to a trip", or typed
   │ "Put on a day"                          │ "Add as an option"
   ▼                                         ▼
Item on a day (leg, stay, do, eat, note) ← Option in an OptionGroup on a day (choose one, votes)
   │ planned → scheduled → booked                │ Pick → its items count as the day's
   ▼                                             │ Split → each option's travellers get its items
Trip finishes → goal's "mark done" prompt        └ Considered (unchosen, kept) → "Save for someday"
```

## Phases

### P1 — Cities: search, route builder, cities that maintain themselves

Done (branch `p1-cities`). As built: the search endpoint is `/locations/cities/search.json` (the app is mounted at
`/locations/`, not `/places/`); a route's planned legs use mode "Other" (a leg always has a mode); a city added from the
box gets coordinates from a lookup, else its country's centre, and no time zone until staff fill it in; "Plan a trip"
keeps adding the goal's cities (they are not "used" by anything until P6's ideas).

- **City search endpoint** `locations:city_search` (`/places/cities/search.json?q=&country=`): approved cities (plus
  the member's own pending ones), ranked like `pages.search` (unaccent, trigram on the name, leading-match bonus),
  up to 10, each `{id, name, region, country, flag, timezone, lat, lng}`. Lives in `locations` (layer 3), so trips
  calls it by URL only. Rate-limited like search.
- **`CitySearchInput` widget** (`apps/locations/widgets.py`, beside `CountryTaggedSelect`): a hidden city id plus a
  type-to-search box (Alpine); shows the trip's cities as chips before typing; carries `data-tz` for the leg zone
  fill (E5). Without JS it falls back to today's grouped select. Replaces the big selects on every trips form: day,
  stay, leg from / to, Trip cities.
- **Not in the catalogue:** "Add “Hallstatt” as a new city" → a small form (name, country, region optional) that
  creates a pending city through the same rules as the existing city submission (visible to its submitter, in the
  approval queue for staff). Usable on the trip at once.
- **Cities maintain themselves:** `apps/trips/trip_cities.sync(trip)` adds to `Trip.cities` every city used by a
  day, stay, leg end, activity / meal place's city and (P6) idea. Called from the forms' saves (replacing the
  per-form joins — `JoinsTripCitiesMixin`, `fill_day_cities`' add, "Plan a trip"). It never removes on its own. Edit
  trip's cities field becomes chips (search to add, × to remove); a city still used by something can't be removed
  ("Used by Day 3, Hotel Laimer Hof").
- **Route builder** (`trips:trip_route`, editors; offered on a new trip and linked from Edit trip and the route
  strip): rows of city search + nights, in order ("Munich 3 → Salzburg 2 → Vienna 4"), starting from the trip's
  current day cities. Saving:
  - sets `Day.city` for each consecutive run of days (days that already have a different city are listed and kept
    unless "Replace" is ticked);
  - ticked by default: a **planned leg** between consecutive cities on the changeover day (no mode, no times;
    "Munich → Salzburg · planned"), skipped where a leg between them already exists that day;
  - ticked by default: a **placeholder stay** per city run ("Stay in Munich", no address; it shows in Not booked
    yet), skipped where a stay already covers those nights;
  - nights that don't add up to the trip's days are shown before saving (extend the trip / leave the rest blank).
  Saved in one transaction under `changes.batch("Route set: …")`.
- **Route strip** at the top of the trip page: "Munich (3) → Salzburg (2) → Vienna (4)" derived from the days'
  cities (consecutive runs), each linking to its first day; editors get "Edit route". From `itinerary.overview`, no
  queries. Not in the booklet (unchanged).
- Tests: search ranking/accents/pending visibility; widget fallback; new city form; sync adds from each source and
  never removes; remove refused while used; route builder fills days, makes legs/stays once, keeps set days,
  reports a mismatch; strip derivation; trip page query count unchanged.
- Help: the guide on starting a trip and adding a day (route builder, city search); bump `updated`.

### P2 — Edit in place: the item panel

Done (branch `p2-item-panel`). As built: plain `fetch` (no htmx, so no CDN pin or offline-worker change); a meal got its
own page (`trips:meal_edit`) since it had none; the day fragment is the trip page's context rendered for one day, so it
costs the page's 32 queries (stays and legs span days); readers open a day's panel from nothing yet (its notes stay
inline on the day), editors through Edit this day; the People tab appears only where the item has travellers (activities,
days).

- On the trip page, an editor's click on an item (leg, stay, activity, meal, section, day header) opens a **side
  panel** (a full-screen sheet below `sm`) with that item's existing page — `leg_edit`, `stay_edit`,
  `activity_edit`, the meal's and section's pages, `day_edit`'s details — fetched with `?panel=1`, which renders
  the page's content block without the site chrome. Saving in the panel re-renders **that day's fragment**
  (`trips:day_fragment`, `/trips/<pk>/days/<day_pk>/fragment/`, the same template the trip page includes) and
  swaps it in; the panel shows "Saved" and stays open. Deleting closes it.
- The panel has tabs: **Details · Booking** (the Confirmations block and files, cost + currency) **· People**
  (travellers on it) **· Contacts** (the Contacts & info block) **· Comments**. Each tab is the existing partial;
  no new data.
- Readers (viewers, commentors) get the same panel read-only with Comments.
- Mechanism: pick **htmx** (pinned version with SRI, per the CDN rule, and added to the offline worker's CDN list)
  or Alpine + `fetch`; record the choice in CLAUDE.md. Panel URLs are outside the offline worker's cached paths.
- Every item page still works on its own (direct links, no JS, `next` back as now).
- The day fragment has its own pinned query count (`test_detail.DayFragmentQueryTests`); the trip page's count
  doesn't change.
- Tests: `?panel=1` renders without chrome for each item kind; permissions (404 / 403 as now); saving returns the
  day fragment; read-only panel for a viewer; no-JS flow unchanged.
- Help: `reading-your-trip`, `adding-a-day` (editing on the trip page); bump `updated`.

### P3 — One-line add and five kinds of item

Done (branch `p3-quick-add`). As built: the Options button comes with option groups (P4); a typed time on a leg goes in
its notes ("Around 09:15") because a planned leg has no times; a catalogue match is offered on a new meal's own page;
`import_itinerary --apply` converts a new trip's sections to notes; tidy reads notes as the types they replaced; the
booklet changed only where a phase's highlights print as "• " lines instead of a list.

- Each open day ends with **+ Add** (editors): one text box plus kind buttons **Travel · Stay · Do · Eat · Note ·
  Options**. Typing then Enter guesses the kind and makes a rough item on that day, then opens it in the panel:
  - "Train Munich → Salzburg 9:15" → a leg (mode, cities via city search matching, time if given — through
    `logistics.py`'s parsing, extended);
  - "Hotel Laimer Hof 3 nights" → a stay checking in that day;
  - "Dinner Augustiner 7:30pm" / "Lunch …" → a meal (type from the word, `reserved_time` from the time; a catalogue
    place matched by `catalogue_links.match_keys` is offered, never linked automatically);
  - "Tour …", "Tickets …", "Museum …", anything else with a time → a trip activity; without one → a note.
  A kind button forces the kind. Parsing is pure (`apps/trips/quick_add.py`) and table-tested.
- **Five kinds on screen.** Travel (`TransportLeg`), Stay (`Lodging`), Do (`TripActivity`), Eat (`Meal`), Note
  (`Section`). Section types collapse in the UI to **Note** (optional heading, tone none / tip / warning /
  critical, paragraphs) and **Travel notes** (as E6). `phase`, `callout` and `free_text` become `note`;
  `logistics_table` stays import-only; `choose_your_adventure` is converted in P4.
- **Conversion** (decision 6): `apps/trips/day_first.py` plans conversions, `trips:trip_convert`
  (`/trips/<pk>/convert/`, editors; linked from the Needs attention banner while anything is left) shows them by day,
  ticked, with before → after; `manage.py convert_day_first --trip <pk> [--apply]` (dry run by default). P3 converts
  phases, callouts and free text to notes (a phase's summary/highlights become paragraphs; a callout's tone is
  kept). One transaction, `changes.batch`. The booklet prints notes as it printed the old types; update the
  snapshot deliberately and review the diff.
- Tests: quick-add parsing table; each kind lands on the right day; conversion dry run vs apply; nothing lost
  (every paragraph present after); booklet snapshot reviewed.
- Help: `adding-a-day` rewritten around + Add; bump `updated`.

### P4 — Option groups and votes

Done (branch `p4-option-groups`). As built: `Vote` has only `option` for now (P6 adds `idea` and the check constraint);
options have no comments of their own (talk about a choice in the day's notes); an option's cost is shown in its own
currency when its costs share one, else converted to the home currency; a decided group prints "Prompt: chosen" in the
booklet so a choice with no items isn't lost; undoing a reopen isn't offered (pick again on the day); a
choose-your-adventure section with a confirmation stays as it is; the day page gained **+ Choose one**.

- **Models** (trips 00xx):
  - `OptionGroup`: trip, day (FK; a stay group sits on its first night), `prompt` ("Afternoon", "Where to stay in
    Munich"), `start_time` (optional, places it in the timeline), `order`, `state` open / picked / split,
    `decided_by`, `decided_at`.
  - `Option`: group, `title`, `notes`, `order`, `chosen` (bool; exactly one when picked — partial unique index),
    `travelers` (M2M, used by split in P5).
  - `option` FK (nullable, SET_NULL → the item falls back to plain day item) on `TransportLeg`, `Lodging`,
    `TripActivity`, `Meal`, `Section`: an item inside an option. An option can also hold no items (just a title,
    notes and an estimated cost: `est_cost` + `currency` via `currencies.setup()`).
  - `Vote`: user, `option` or `idea` (P6; exactly one — check constraint), unique per user + target.
- **On the day:** an open group renders where it sits in the timeline as a box: each option's title, its items
  (compact rows), total estimated cost (in home currency, `budget.estimate`'s rules), total time when known, 👍 and
  who voted, comment count; editors: **Pick**, **+ Option**, edit. Picked: the chosen option's items render as the
  day's own items (in the timeline) with a small "Chosen from: Afternoon (2 options)" that reopens the Considered
  list; unchosen options fold into **Considered** (reopen, "Save for someday" in P6).
- **What counts:** only items that are not in an option, or are in a chosen option (or, for split, the viewer's
  option — P5), feed the timeline, `not_booked`, Needs attention, the budget estimate, the calendar feed, the map
  and the day summary line. One rule in `itinerary` (`counts(item, viewer)`), used by all of them. An open group
  adds "1 undecided" to the day's ⚠ and the banner ("N decisions"), and the calendar feed shows it as one all-day
  "Undecided: A / B" event.
- **Votes:** `trips:option_vote` (POST toggle, `comment` capability; 204 for fetch). Shown to everyone on the trip;
  never public.
- **Booklet:** an open group prints "Afternoon — undecided" with each option's items; a picked one prints only the
  chosen items. Snapshot updated deliberately.
- **Conversion** (in `day_first.py` / the convert page): `choose_your_adventure` sections → an `OptionGroup` on the
  same day (prompt = the section's prompt, an `Option` per option with description → notes, duration/cost text
  kept in notes); decision `BookingTask`s with `TaskOption`s → an `OptionGroup` on the task's day (else its
  leg/stay/activity's day, else Day 1 flagged for review), chosen option kept as picked, option URL/cost carried
  over; the task is closed with a note pointing to the group. After conversion the "Decide" kind is no longer
  offered on new to-dos (the To do page lists open groups instead); `TaskOption` stays readable for history.
- History/undo: picking, reopening, splitting record a `TripChange`; undo reopens.
- Tests: what-counts rule across views (timeline, not booked, budget, calendar, map); pick/reopen; votes toggle and
  permissions; conversion of both sources; booklet snapshot; trip page query count (one more prefetch for groups,
  options, votes — re-pin with the reason).
- Help: a new guide `options-and-votes`; update `reading-your-trip`, `bookings-and-confirmations`; bump `updated`.

### P5 — Split

Done (branch `p5-split`). As built: no migration (`Option.travelers` and the `split` state came with P4); the people to
split are the day's roster (its own group, else the trip's travellers); at least two options must be taken (everyone on
one is a pick); options nobody takes fold into Considered; a split's time is its own or its earliest item's; the day's
summary line still names either track's activities; a tracked stay never becomes the day's "Sleeping" stay (its other
nights say "Sleeping (who): …"); undo on a split reopens it.

- An open group's **Split** (editors): assign travellers to options (each traveller on at most one option of a
  group; everyone must be placed; `Option.travelers`). State `split`.
- The day shows **tracks**: the timeline gains a column per option on phone-friendly stacked rows ("Debbie, John:
  BMW Welt …" / "James, Sara: Deutsches Museum …"), shared items above and below. Items inside an option inherit its
  travellers for "who's on it" (calendar `?mine=1`, activity travellers when blank).
- Legs and stays inside an option follow it ("we take the 17:05 back, they stay for dinner and take the 21:30").
- Booklet: tracks side by side when two, stacked with names when more. Snapshot updated deliberately.
- Tests: assignment rules; the calendar feed's `mine` per traveller; timeline tracks; budget estimate per track
  (totals add both tracks); booklet snapshot.
- Help: `options-and-votes` (split); bump `updated`.

### P6 — Ideas shelf and the bucket-list link

Done (branch `p6-ideas`). As built: `kind_hint` is optional — an idea's kind otherwise comes from its catalogue link (a
Food & drink place is somewhere to eat; an event, activity or place something to do; else a note) and "Put on a day"
lets the editor pick another; "Add as an option" makes the option and, for a catalogue-linked idea, its item inside it;
a goal becomes an idea only when its owner may comment on the trip (a viewer's goal is just linked, as before); a goal
counts as its owner's vote (a `Vote` is made); goals about the same catalogue item share one idea; "whose goal" reads
"Debbie's goal" / "Debbie's and your goals"; the `trip_goals` page is kept (your goals on the trip, remove, add others)
and returns to the shelf instead of redirecting; Add to a trip is on city pages too; the shelf loads on the trip page
only (38 queries; the day fragment stays 36); ideas are in the change history and the Your data export, not in the
booklet or calendar.

- **`TripIdea`** (trips): trip, `title`, `notes`, optional catalogue link (`city` / `poi` / `activity` / `event`, at
  most one), `added_by`, `kind_hint` (travel / stay / do / eat), `placed_type` + `placed_id` (generic link to the
  item or option made from it; null while on the shelf), `created`. Votes via `Vote.idea`.
- **The shelf** on the trip page: a fold after About this trip ("Ideas · 7"), each idea with who added it, its
  place, 👍, and for editors **Put on a day** (pick a day → creates the item of its kind pre-filled from the idea and
  its catalogue link, opens it in the panel) and **Add as an option** (to an existing group on a day, or a new
  group). When the placed item or option is deleted, the idea returns to the shelf.
- **Adding ideas:** a typed idea on the shelf (`comment` capability); the catalogue's place / activity / event pages
  get **Add to a trip** (shell partial `partials/_trip_add_button.html`, `url … as`, so catalogue apps don't import
  trips) listing the member's trips they may comment on.
- **Map:** an **Ideas** layer of faint pins for ideas with a place (their POI, activity venue, event venue or city),
  off by default, from `trip_map_data` (no new endpoint).
- **Bucket-list link** (`bucketlists` → `trips` is allowed; never the reverse): `BucketListItem.trip_idea` (FK,
  SET_NULL) replaces "goal is on that trip" as the precise link (`item.trip` stays, derived from the idea's trip on
  save). "Plan a trip" / "Add to a trip" from a goal creates a `TripIdea` copying the goal's target (never its
  personal notes) and links it. On the shelf the idea shows "Debbie's goal" through the shell partial
  `partials/_idea_goals.html` (`url … as` → `bucketlists:idea_goals`, loaded after the page, so trips doesn't
  import bucketlists). Several people's goals on one idea count as their votes.
- **Done:** when a trip finishes, the existing bucket prompt goes to each goal whose idea was placed on an item that
  counted (P4's rule) — `bucketlists:trip_done` reads it through the idea; goals whose ideas never left the shelf
  or sat in unchosen options aren't offered "mark done".
- **Save for someday:** on a shelf idea or a Considered option, **Save for someday** (shell partial →
  `bucketlists:save_idea`) adds a goal for the clicking member (target from the catalogue link, else custom title);
  refused if that target is already on their list (link to it instead).
- Existing data: goals with `item.trip` and no idea get one created by a data migration (unplaced), so they appear
  on their trip's shelf; existing `trip_goals` page redirects to the shelf.
- Tests: shelf CRUD and permissions; put on a day for each kind; return to shelf on delete; catalogue Add to a trip;
  map layer; goal → idea link both ways (layer check stays clean); done prompt only for counted items; save for
  someday duplicates refused; the data migration.
- Help: `options-and-votes` (ideas) or a new `ideas-and-goals` guide; the bucket-list guide; bump `updated`.

### P7 — Trip-wide views read-only; Edit trip becomes Settings

- **To do** (`trip_todo`) lists, in order: open option groups ("Decide: Afternoon on Day 4"), not-booked items,
  then hand-written to-dos. **Bookings** (Reference's confirmations), **Getting around**, **Costs** (Budget),
  **Map**, **Calendar**, **Booklet**: every line links to `trip_detail#<anchor>` and opens the item's panel there;
  none of them has add/edit forms except the Budget page's own costs and rates.
- **Edit trip → Settings** (`trips:trip_settings`; `trip_edit` redirects): name, dates (changing dates offers to
  add/remove days at the ends), status, home currency, travellers, cities (chips, P1), People link, Checklists,
  Loose confirmations, trip-wide Contacts & info. **All stays & legs** moves to the Bookings view (read-only, Edit
  opens the panel on the trip page). The day page (`day_edit`) stays as the no-JS fallback and the panel's day
  details; its Add to this day mirrors + Add.
- Header: **Edit trip** becomes **Settings** (editors); the jump bar gains **Ideas** when the shelf has any.
- CLAUDE.md: rewrite "The view page is for reading; adding is on the day page…" and "Edit this day" to describe the
  panel, + Add, option groups, the shelf and Settings; update "Decisions are tasks with options" (converted to
  option groups in P4).
- Tests: every view's links open the right anchor; Settings saves; date change offers days; old URLs redirect;
  `EditTripQueryTests` re-pinned for Settings; `test_help_links`.
- Help: every guide naming Edit trip; bump `updated`.

## Not changing

- Access rules (`TripGrant` roles; 404 / 403), the public view (no ideas, options, votes or groups in it;
  `audit_public_leak` green), the change history (new kinds added to `TRACKED` / `RESTORABLE` where they fit), the
  offline page (read-only offline), confirmations and files, catalogue notes on items.
- The booklet's layout apart from the deliberate snapshot updates named in P3–P5.

## After P7

Set this plan's status in CLAUDE.md ("### Day-first planning") and remove anything the phases made untrue.
