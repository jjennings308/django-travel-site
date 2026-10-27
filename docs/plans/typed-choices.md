# Plan: typed choices (a "choose one" knows what it's choosing)

Status: T1 done (2026-10-27, branch `t1-choice-kinds`); T2 done (2026-10-27, branch `t2-pick-makes-item`). Decisions by James 2026-10-27 ("your call" — listed below). Phases T1–T3, one
branch each, in order. Read with `CLAUDE.md` → Trips → "'Choose one' groups and votes", "Split", "Ideas shelf" and
"+ Add and five kinds", and `docs/plans/day-first-planning.md` (P4–P6).

## Why

A choice (`OptionGroup` + `Option`) is generic today: an option is a title, notes, a link and a cost. To compare
six Augsburg hotels properly you'd have to create six stays (with dates and addresses) and put each "In option";
to compare tents, six activities. And picking an option creates nothing — the real stay, meal or activity is
added by hand afterwards. A choice should know **what kind of thing** it decides, ask each option only for what's
needed to compare, and **turn the winner into the real item** when an editor picks it.

## Decisions (James, 2026-10-27)

1. **Picking copies once.** The chosen option's details are copied into a new item; from then on the item is the
   record (no two-way sync). The option keeps what it had, for Considered and history.
2. **Stay length lives on the choice** (check-in day = the choice's day, `nights` on the group); an option may
   override nights (e.g. an Airbnb with a 3-night minimum) — blank means the group's.
3. **Ideas and the map come in a later phase (T3)**, after kinds, comparison and pick-creates-item work.

## The model

- `OptionGroup.kind`: `any` (default — today's behaviour, items added "In option" by hand), `stay`, `eat`, `do`,
  `travel`. Shared fields for the kind, all optional:
  - stay: `nights` (positive small int);
  - eat: `meal_type` (the `Meal` types), and the existing `start_time` is the reservation time;
  - do: the existing `start_time`, plus `end_time`;
  - travel: `mode`.
- `Option` gains, all optional: `poi` / `activity` / `event` / `city` (catalogue link, at most one — check
  constraint like `tripidea_one_target`; SET_NULL), `place_text` (typed place or address), `nights` (stay
  override), `from_text` / `to_text` (travel), and `made` (generic link to the item Pick created; null until then).
  `url`, `est_cost` + `currency` (via `currencies.setup()`), `notes` stay. For a stay, `est_cost` is **per night**
  (label it so); everywhere else it's the total.
- One migration; existing groups become `any`, existing options keep everything. Choices only on `kind`; check with
  `sqlmigrate` that nothing is dropped.

## Phases

### T1 — Kinds and the options' fields

Done (branch `t1-choice-kinds`). As built: + Add's **Options** and + Choose one guess the kind from the prompt and the
choice's page changes it (no extra question first); saving a changed kind stays on the page so the options can be
filled in; a stay option's cost counts × 1 while no nights are known; the line shows the option's catalogue place as a
link; the travel line has no duration (options have none until T2's legs); the snapshot fixture gained an open stay
choice (two options, one with its own nights).

- `OptionGroupForm`: **What is this choice about?** (Stay / Eat / Do / Travel / Anything) and the kind's shared
  fields (nights; meal type + time; start / end; mode). `OptionFormSet` shows only the fields for the kind (title,
  link, cost and notes always; plus place — catalogue search or typed — for stay / eat / do; nights override for
  stay; from / to for travel). The catalogue pickers reuse the trip forms' place choices
  (`forms.catalogue_places` — Food & drink first for eat —, `catalogue_activities`, `catalogue_events`, the city
  search box) and are built once per page (`share_choices`).
- **+ Add**: the **Options** button asks for the kind (the typed line becomes the prompt; "Where to stay…" /
  "hotel" → stay, "dinner / lunch / breakfast" → eat, "train / flight / drive" → travel, else do — pure, in
  `quick_add.py`, overridable on the group page). The day page's **+ Choose one** does the same.
- The box on the day: per option, the kind's line — stay "€95/night × 3 = €285 · Maximilianstraße"; eat "Augustiner
  Bräustuben · €40"; do "Hacker-Festzelt · 11:00–16:00"; travel "Train Augsburg → Munich · ~45 min" — then votes as
  now. The option's total (stay: nightly × its nights) feeds the existing `option.cost` and so the estimate rules.
- Items already "In option" keep showing under their option (any kind); nothing about that changes.
- Booklet: an open typed choice prints the same one-line summary per option; update the snapshot deliberately.
- Tests: form fields per kind; prompt → kind guesses; stay total; catalogue pickers query once; migration keeps
  existing groups as `any`; trip page query count unchanged (fields are on rows already fetched).
- Help: `options-and-votes` (kinds); bump `updated`.

### T2 — Pick creates the item

Done (branch `t2-pick-makes-item`). As built: the pick's history line and the item's "Added …" line are recorded
separately, not inside one `changes.batch` — a batch would fold the pick into a summary line, and Undo needs the pick's
own line to reopen the choice; the option's link goes into the item's notes (no contact / info link); a stay with no
nights known gets one night; an activity's kind is read from its title (+ Add's rule), a ticket for an event; a
deleted made item is made again on the next pick. The pick opens the new item through P7's `?item=` link.

- `options.make_item(option)` (one place; used by Pick and by Split): for `stay` → a `Lodging` (name = title,
  address = place text, city = the catalogue city / place's city, check-in = the group's day's date, check-out =
  + nights (option's, else the group's), nightly rate + currency from `est_cost`, notes, the option's link in
  notes or a contact/info link); `eat` → a `Meal` on the day (type, `reserved_time` = group time, name / `poi` from
  the option); `do` → a `TripActivity` (title, `poi` / `event` from the option, start / end, `est_cost`); `travel` →
  a planned `TransportLeg` (mode, from / to text, cities matched like `leg_quick_add`, date = the day, zones from
  cities). The new item is saved **inside the option** (`item.option = option`), so it counts because the option is
  chosen, and `option.made` points at it. `trip_cities.sync` after.
- **Pick** on a typed choice: picks, makes the item if `option.made` is empty (an option that already has items "In
  option" makes nothing — it has its real item), and opens the new item in the panel ("Picked Rugs Hotel — add the
  address and confirmation"). On `any` choices Pick is unchanged.
- **Reopen**: nothing is deleted; the made item stays inside its option and stops counting (today's rule). Picking
  the same option again reuses `option.made`; picking another makes that option's item.
- **Split** on a typed choice: makes the item for each taken option (each on its track).
- History: the made item is recorded as added (actor = the picker), inside the pick's `changes.batch`; undoing the
  pick reopens and leaves the item in Considered.
- Tests: each kind makes the right item with the right dates / time / place / cost; nights override; the item
  counts (timeline, Not booked yet, Sleeping lines, estimate, calendar, map) only while picked; re-pick reuses;
  split makes one per track; `any` unchanged; panel opens on the new item (JSON for fetch).
- Help: `options-and-votes` ("Picking a stay, meal or activity adds it to the day"); bump `updated`.

### T3 — Ideas and the map

- **Ideas → Add as an option**: offers the open choices whose kind fits the idea's kind (any always fits) and
  copies the idea's title, notes and catalogue link into the option's fields (`ideas.fill` gains an option branch);
  a new choice made from an idea gets the idea's kind.
- **Map**: options of open typed choices with a place (catalogue place / venue / city) are faint pins in a
  **Choices** layer (popup: the choice's prompt, the option, its votes), off by default, from `trip_map_data`
  (one more query there only).
- **Catalogue notes while deciding**: an option linked to the catalogue shows its Good to know notes under it in the
  box (same `trip_notes` rules, folded to one line "3 notes"), so "closed Mondays" or "book 3 months ahead" counts
  before anything is picked.
- Tests: kind matching; fill; map layer features and switch; notes under options; trip page pin re-pinned with the
  reason if the notes add a query.
- Help: `ideas-and-goals`, `options-and-votes`; bump `updated`.

## Not changing

- Votes, Considered, Reopen, Split's rules and "what counts" (`counts_q`, `options.counts`).
- The public view (never shows choices), access rules, the calendar's "Undecided: A / B" event.
- Choices made before T1: they stay `any` and behave exactly as now.
