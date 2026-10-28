# Plan: a planned budget — every item can carry an estimate, with its basis

Status: B1 done (2026-10-28, branch `b1-cost-basis`); B2 done (2026-10-28, branch `b2-planned-budget`). Asked for by James 2026-10-28. Three phases, one branch each, in order: B1 (what a cost means:
a basis on every item's cost), B2 (the Budget page shows estimated → booked → paid, by category and per person), B3
(costs where you plan: on the day's rows, in choices, and payments recorded against what they paid for). Read with
`CLAUDE.md` → Trips → "Budget", "Budget in one currency", "Currency choices", "Typed choices", "Booking tasks cover
their items" and "No booking needed".

## Why

James plans in detail ("I may deviate in real life, but I want the plan as a foundation") and wants the Budget page to
grow from actuals into a planned budget: what the trip should cost, what's booked, what's been paid, per category and
per person. Today:

- **Costs have no meaning attached.** A leg's `cost`, a stay's `nightly_rate`, an activity's / option's `est_cost` are
  bare numbers. Nothing says whether €95 is the whole booking, per person, per night, or per room per night — so the
  site can't make a total or a per-person share. A stay for six in Germany is three hotel rooms or one 3-bedroom VRBO;
  that difference has to be expressible.
- **Meals can't carry a cost at all**, and things that need no booking (the €8 castle museum at the door, lunch, the
  U-Bahn) have nowhere sensible for an estimate. A cost must not depend on a booking.
- **The trip estimate double-counts.** `budget.estimate` adds every confirmation's `cost` *and* every activity's
  `est_cost`, so an activity with both is counted twice; legs and stays are never counted unless booked.
- **The Budget page is actuals only** (`TripExpense`), by currency, with settle-up.

## Decisions (James and Claude, 2026-10-28)

1. **One cost on every plannable item, with a basis.** Legs, stays, trip activities, meals and choice options each
   have an estimate (amount + currency, as today's fields), a **basis**, and where it matters a **quantity**. The
   site works out the item's total and each person's share; nothing is stored twice.
2. **Bases** (`costs.Basis`), offered per kind:
   - *total* — the whole thing, for everyone it covers (legs, stays, activities, meals, options);
   - *per person* (legs, activities, meals, options);
   - *per night* — the whole stay per night (stays, stay options);
   - *per room per night* — with **rooms** (stays, stay options);
   - *per person per night* (stays, stay options).
3. **People** for a per-person basis or a share: the item's own travellers (activities, a split option's
   travellers), else the day's roster (`day.roster`), else the trip's travellers; an optional **people** number on the
   item overrides (a leg for 4 of the 6). Shares are split evenly among them; nobody's share is guessed when the count
   is unknown — the row says "people not set".
4. **Booked replaces estimated.** When a confirmation with a `cost` covers items, that booking's cost is the figure
   for them (once, however many items it covers — GCH7JS on four legs is one booked line), and their estimates step
   aside. Paid (expenses) is shown next to it, never added to it.
5. **What counts** is the trip page's rule (`counts_q` / `options.counts`): items outside any choice or in a chosen /
   split-taken option. Open choices show as a range ("Undecided: €840–€1,240"), not in the total.
6. **A daily food allowance** per person per day on the trip (optional) covers food not listed as a meal with its own
   estimate; it skips days marked `meals_included`. Its line says so.
7. **Not public, not in the booklet** (B1–B3). The booklet is unchanged; the snapshot must not move.

## B1 — What a cost means (branch `b1-cost-basis`)

- **Model** (one trips migration; read it with `sqlmigrate`, no `RemoveField`): on `TransportLeg`, `Lodging`,
  `TripActivity`, `Meal` and `Option`: `cost_basis` (CharField, choices from `costs.Basis`, blank = the kind's default),
  `cost_people` (PositiveSmallIntegerField, null — overrides the people count). `Lodging` and `Option` also get
  `rooms` (PositiveSmallIntegerField, null). `Meal` gains `est_cost` + `currency` (blank). Existing amount fields keep
  their names (`TransportLeg.cost`, `Lodging.nightly_rate`, `est_cost`); `costs` reads them through one accessor per
  kind (`costs.amount_of(item)`), so nothing else renames.
- **Defaults keep today's meaning** (no data migration needed; say so in the PR): a leg's `cost` and an activity's
  `est_cost` = *total*; a stay's `nightly_rate` = *per night*; a stay option's `est_cost` = *per night*, other options
  *total*; a meal = *per person*.
- **`apps/trips/costs.py`** (pure, no queries): `Basis`, `BASES_FOR` (kind → allowed bases), `people_for(item, day,
  trip)` (the rule in decision 3, from prefetched travellers; returns `(count, known)`), `nights_for(item)` (a stay's
  nights; a stay option's `stay_nights`), and `estimate(item, …)` → `Cost(amount, currency, basis, people, nights,
  rooms, total, per_person, line)`. `line` is the one wording used everywhere: "€95 per room per night × 3 rooms × 4
  nights = €1,140 · €190 each (6)", "€310 per night × 4 nights = €1,240 · €207 each (6)", "€8 per person × 6 = €48",
  "€62 total · €15.50 each (4)". Money in cents (`budget._cents`), the remainder on the first share (as `budget.shares`
  does). Unknown people → total only, "people not set". Missing nights on a per-night basis → "× ? nights".
- **Forms** — one shared piece, `forms.CostFieldsMixin` (amount, currency via `currencies.setup()`, basis select
  limited to `BASES_FOR[kind]`, people, rooms shown by Alpine only for *per room per night*, all optional; the no-JS
  form shows every field), used by the stay, leg (`TransportLegForm` / `LegEditForm` — the return trip copies basis and
  people but, as today, not the amount), activity, meal page (`MealPageForm`; the day's Meals formset gets amount +
  basis only), and `OptionForm` (by kind: a stay option gets the stay bases and rooms). A live preview line under the
  fields (Alpine, same arithmetic as `costs.line` for display only; the saved figure is always computed in Python).
- **Typed choices**: `Option.own_cost` / `kind_line()` move onto `costs.estimate`, so "€95 per room per night × 3 rooms
  × 4 nights" shows in the choice box and compares directly with "VRBO €310 per night × 4"; `options.make_item` copies
  the basis, rooms and people onto the stay / meal / activity / leg it makes.
- **Fix the double count now**: `budget.estimate` (About this trip) becomes `costs.planned_total(trip)` — per item,
  the booked cost if a costed confirmation covers it (each confirmation once), else the item's estimate — from the trip
  page's prefetch. Pins must hold (`test_detail` 38, fragment 36): legs, stays, meals and options already come in the
  prefetch; activities' and options' travellers are prefetched; `day.roster` uses the prefetched `travelers` /
  `trip__travelers` (check, and add the prefetch to the page queryset only if it costs no query — if it does, re-pin and
  say why).
- **History**: the new fields join `changes.TRACKED` for their kinds ("cost: €95 per night → €95 per room per night ×
  3 rooms").
- **Tests** (`tests/test_costs.py`, pure): every basis × kind; people from travellers / roster / trip / override /
  unknown; nights from a stay and a stay option; cents and remainders; the wording; the old meanings unchanged for
  existing rows; `planned_total` counts a confirmation once across four legs and drops those legs' estimates;
  options and `make_item` carry the basis; form validation (basis not allowed for the kind refused; rooms only with per
  room per night); pins.
- **Help**: `budget` (and a line in `bookings-and-confirmations`):
  what each basis means, the 3 rooms vs VRBO example; bump `updated`.

## B2 — The planned budget page (branch `b2-planned-budget`)

- **`apps/trips/costs.py` → `plan(trip, target, today)`** (pure over the Budget page's own prefetch; the page is
  separate from the trip page, so its count is free to grow but must be fixed per page, not per item — pin it in
  `test_budget`): rows by **category** — *Travel* (legs), *Stays*, *Activities & tickets* (activities), *Food*
  (meals with estimates, then the allowance line), *Other* (loose confirmations with a cost, e.g. insurance). Each row:
  item (or a booking covering several items: "GCH7JS · 4 flights"), day, **estimated**, **booked**, **per person**,
  people, and status (no plan / estimated / booked / no booking needed). Undecided choices are listed under their
  category as a range and left out of the totals. Every amount converted to the page's currency (`?in=`, default the
  reader's preferred currency, as the actuals already do) through one `Rates` load; an unknown currency is listed,
  never guessed.
- **Totals** per category and overall: *Planned* (booked where booked, else estimated), *of which booked*, *Paid*
  (the existing expenses, by their `category`, converted the same way), and *Left to pay* (planned − paid, never below
  zero per category). A per-person table: each traveller's share of the plan (from the rows' people) next to what they
  have paid so far (the existing `summarize`).
- **Food allowance**: `Trip.food_allowance` + `food_allowance_currency` (null / blank; one migration), set in
  Settings → The trip ("Daily food per person, for meals you haven't priced"); the row is "€45 per person per day × 11
  days × 6 = €2,970" (days with `meals_included` skipped; people per day from the roster).
- **Page layout** (`trip_budget.html`): **Plan** first (the category table, folded rows per category on a phone,
  ⓘ on a row shows its `line`), then **Spent** (today's expenses list, unchanged), then **Settle up** and **Your own
  rates** (unchanged). Rows link to the item on the trip page (`?item=` opens it in the panel), where its cost is
  edited — the Budget page itself stays read-only for the plan. Add a cost (an actual) stays where it is.
- **About this trip**'s estimate becomes the plan's total with its "booked of planned" ("≈ $14,200 planned · $6,100
  booked"), linking to the Budget page.
- **Tests**: rows and categories; a costed confirmation over several items is one row and their estimates aren't
  added; booked + estimated mix; undecided ranges excluded from totals; allowance and `meals_included`; per-person
  table; currency conversion and an unknown currency listed; the page's fixed query count; the trip page's pins
  unchanged.
- **Help**: the budget guide's Plan section; bump `updated`.

## B3 — Costs where you plan, and payments against items (branch `b3-costs-in-place`)

- **On the day**: each leg / stay / activity / meal row shows its estimate quietly at the end ("≈ €190 pp" or "€1,140
  · booked") when it has one, from `costs` (no queries; the trip page's pins hold). The day's summary line does **not**
  get a cost (keeps it short). The booklet stays unchanged.
- **Choices**: each option shows total and per person on the same basis; the box ends "Cheapest per person: B" when
  two or more options have costs for the same people.
- **Paid against what it paid for**: `TripExpense` gains an optional generic **For** (an item or a confirmation of the
  same trip; one migration, `content_type` + `object_id`, checked like `ConfirmationLink.link`). The Plan's rows then
  show paid per row, not only per category. A booked row on the Budget page (editors) has **Record a payment**, which
  opens the add-cost form pre-filled (description, amount = booked cost, currency, category from the row, For = it).
  An expense without For counts in its category only, as today.
- **Your data** export: the cost fields and an expense's For (as a label). `audit_public_leak` unchanged (none of
  this is public).
- **Tests**: row text on the day; the trip page's pins; option comparison; expense For validation (another trip's
  item refused); Record a payment pre-fill; paid per row; export.
- **Help**: the budget guide and `reading-your-trip`; bump `updated`.

## Not changing

- Settle-up, the trip's own rates and the ECB rates.
- Confirmations remain the booked figure; an expense remains what was paid.
- The public view and the booklet.
