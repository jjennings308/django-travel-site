# Plan: edit by day (Edit trip keeps only trip-level things)

Status: E1 done (2026-10-26, branch `e1-stays-from-day`; the new stay starts in its day's city, editable); E2 done (2026-10-26, branch `e2-todo-page`; the To do page skips the "Looks like" suggestions, which stay on the trip page); E3–E6 not started. Decisions answered by James 2026-10-25 ("recommended for all"; listed
below). Phases E1–E6, one branch each, in order. Read with `CLAUDE.md` → Trips, especially "Edit this day",
"The view page is for reading; adding is on Edit trip", "Confirmations attach like comments", "Booking tasks
point at their item", "Budget in one currency" and "Maps" (stays).

## Why

The trip page now reads **day by day** (the folded days are the overview), and the day page already has
**Add to this day** and **On this day**. Edit trip is still shaped like the database: long formsets of every
stay, leg, confirmation, contact and booking task for the whole trip, each row with 200-option city selects,
typed IANA time zones and typed latitude/longitude. So the same things are added in two places, and the
trip-wide way is the hardest one to use.

The rule after this plan: **things that happen on a day are added and edited from that day; Edit trip holds
only what belongs to the whole trip.** Records do not move: a stay and a leg still belong to the trip (a stay
spans nights; a leg can cross midnight or change date) and are *placed* on days by their dates, as now.

## Decisions (James, 2026-10-25)

1. Remove Edit trip's stay and leg formsets; keep a read-only **All stays & legs** list with Edit links.
2. **Home currency** is a setting on the trip, defaulting to the creator's preferred currency.
3. Currency selects keep an **Other…** choice (typed three-letter code).
4. A stay with a city but no found address shows the **city's pin without saving it** (`Lodging.pin()` already
   falls back to the city), so a later address lookup still runs.
5. **Exchange rates move to the Budget page.**
6. **"Also add the return trip"** stays on the leg's own page (`leg_edit`'s Return group), reached from the day.
7. Booking tasks get a small trip-level **To do** page, linked from the Needs attention banner, instead of the
   formset.
8. **Logistics tables fold into travel notes** in this plan (E6).

## End state of Edit trip

- **The trip:** name, dates, destination, status, cities, notes, travellers, **home currency** (new).
- **Days:** the existing table (each with Edit this day, `next` back here), add/delete days.
- **All stays & legs** (read-only): every stay and leg in date order, one line each through the existing
  rows (`_stay_card` compact / `_leg_row` compact), with confirmation chips, its day, and **Edit** (→
  `stay_edit` / `leg_edit` with `next` back here). Stays outside the trip's days and legs on no day are flagged
  as now. Replaces today's **Travel by day** and **Bookings & confirmations** sections.
- **Loose confirmations** (insurance, rail pass): list + "Add a loose confirmation" (`confirmation_new`).
- **Contacts & info** (trip-wide): the existing list of contact/info pages (the Contacts formset goes).
- **Checklists**, **People** link — unchanged.
- Gone: the Lodging, Transport, Confirmations, Contacts and Booking tasks formsets, and Exchange rates
  (→ Budget).

## Phases

### E1 — Stays are added and edited from the day

- New pages (editors): `trips:stay_new` (`/trips/<pk>/days/<day_pk>/stays/new/`: check-in = that day's date,
  check-out = the next day; both editable, multi-night is normal), `trips:stay_edit`
  (`/trips/<pk>/stays/<stay_pk>/`), `trips:stay_delete`. Use `LodgingForm` (keeps `LocatingStayMixin`:
  geocoding, `fill_day_cities` and its "N days given a city" message). `next` handled like `leg_edit`
  (`url_has_allowed_host_and_scheme`), default back to the check-in day's page `#on-this-day`.
- The stay page shows the same **Confirmations** block as the leg page (`partials/_item_confirmations.html`)
  and the **Contacts & info** block (`partials/_item_links.html`), so a hotel's confirmation number and phone
  are added in one place.
- Latitude/longitude move into a closed **"Adjust the pin"** `<details>` with one line: "Found from the
  address. Without an address the map uses the city's centre." Nothing is copied from the city
  (decision 4).
- Day page: **+ Stay** in Add to this day (between Leg and Activity). "On this day" lists the stay
  checking in that day (and "Sleeping: …" / check-out lines) with Edit → `stay_edit`.
- Trip page: the stay card's editor Edit link → `stay_edit` (with `next` = `trip_detail#stay-N`).
- `trips:option_add` for a stay option redirects to `stay_new` pre-filled (on the option's day if the task
  has one, else Day 1) instead of Edit trip's blank row; `_stay_from_option` moves with it.
- Change history, undo/restore and the digest already cover `Lodging`; check the new pages record the actor.
- Tests: create/edit/delete from the day; check-in default; `next` safety; 404 without a grant, 403 for a
  viewer; geocoding called once (patched); option → pre-filled stay page; the trip page's query count unchanged.
- Help: `adding-a-day` (+ Stay), `bookings-and-confirmations` (hotel confirmations on the stay page); bump
  `updated`; `test_help_links` covers the stay page's "How this works".

### E2 — Booking tasks: To do page and add from the item

- `trips:trip_todo` (`/trips/<pk>/todo/`, anyone who can see the trip): open tasks by priority and due date,
  then done ones folded; each shows its item ("For: Day 4 · Munich → Salzburg") and Decide options as in
  Reference. Editors: **Add a to-do**, Edit, Mark done, Options (decisions).
- `trips:task_new` / `task_edit` / `task_delete` (editors), using `BookingTaskForm` (item pickers scoped to the
  trip as now). `?leg=` / `?stay=` / `?activity=` pre-pick the item; `next` back.
- From items: the leg, stay and activity pages get **Add a to-do for this** (→ `task_new?leg=…`). Their
  "Still to book" lines link to `task_edit`.
- Needs attention banner: "to do" and "decisions" link to `trip_todo`. Reference → Still to book keeps its
  list and adds "All to-dos" → `trip_todo`.
- `task_offer`, `task_link`, `task_options` unchanged.
- Tests: list order; add with a pre-picked item; scoping (an item of another trip is refused); permissions;
  banner links.
- Help: the guide that covers booking tasks/decisions; bump `updated`.

### E3 — Slim Edit trip

- Remove the Lodging, Transport, Confirmations, Contacts and Booking tasks entries from
  `TRIP_SUBSECTION_FORMSETS` (and Exchange rates — see below); remove **Travel by day** and **Bookings &
  confirmations**; add **All stays & legs** and **Loose confirmations** as described above. The Contacts &
  info and Checklists sections stay.
- **Exchange rates → Budget page:** the `TripRate` formset moves to `trips:trip_budget` under "Rates used"
  as **Your own rates** (editors edit, everyone sees), saved by its own form (POST to
  `trips:trip_rates`, back to the budget page). Explanation line stays ("Leave the ECB's daily rates alone by
  adding none").
- Keep `LodgingForm` / `TransportLegForm` (used by the new pages and the leg page); delete only formset
  classes nothing uses. The admin is unchanged.
- `EditTripQueryTests` (`test_upkeep`): the count should drop; re-pin it at the new number. `perf_report`
  before/after on dev's copy of production.
- CLAUDE.md: rewrite "The view page is for reading; adding is on Edit trip." to "adding is on the day page
  (Add to this day) or the item's own page; Edit trip holds trip-level things", and fix the mentions of Edit
  trip's Transport / Lodging / Contacts formsets (Phase A note, "Round trips", "Booking tasks point at their
  item", "Decisions", "Contacts and info notes", "Budget in one currency").
- Tests: the removed sections are absent; All stays & legs lists every stay and leg with working Edit links
  and flags strays; saving Edit trip no longer touches stays/legs; rates save from the Budget page.
- Help: `adding-a-day`, the Edit trip guide(s), `bookings-and-confirmations`, the budget guide; grep every
  guide and the FAQ for "Edit trip" and the removed section names.

### E4 — Currency choices: home + local

- `Trip.home_currency` (CharField 3, blank=False). Migration: add with default `USD`, then a data step sets each
  trip from its creator's `AccountSettings.preferred_currency` when it has one. New trips default to the
  creator's; shown on Edit trip under The trip.
- `apps/trips/currencies.py`: `choices_for(trip, *cities_or_countries)` → `[home, local…]` (deduplicated,
  home first), locals from `Country.currency_code` (blank codes skipped). The trip's country codes are loaded
  once per page (cache on the trip object like the city choices) so a page doesn't query per row.
  Which places count:

  | Field | Local currency from |
  |---|---|
  | `Lodging.currency` | its `city`'s country, else the trip's countries |
  | `TransportLeg.currency` | `origin_city` and `destination_city` countries (US → DE gives USD, EUR) |
  | `TripActivity.currency` | its `poi`'s city, else the day's city |
  | `TaskOption.currency` | the task's item (as above), else the trip's countries |
  | `Confirmation.currency` | its linked items' places, else the trip's countries |
  | `TripExpense.currency` | its `day`'s city, else the trip's countries |
  | `TripRate` from/to | every currency used on the trip, plus home |

  "The trip's countries" = the countries of `Trip.cities` and the days' cities.
- A shared widget `CurrencySelect` (in `apps/core/widgets.py` beside the date widgets): a select of the given
  codes plus **Other…**; choosing Other reveals a 3-letter text box (Alpine; without JS the text box shows).
  A stored value not in the list is shown selected (labelled as is), never silently changed. Validation
  stays "three letters", uppercased.
- Blank stays allowed where the model allows it (activity, confirmation, option); a new row defaults to the
  item's local currency when there is exactly one, else home.
- Tests: Germany offers USD/EUR, UK USD/GBP; a US→DE leg offers both; Other accepts `CHF`; an existing odd
  value round-trips; no extra queries per row (formset/page query counts unchanged); budget totals unchanged.
- Help: budget/costs guide mentions the choices; bump `updated`.

### E5 — Fill in from the catalogue

- **Leg time zones from cities:** picking From/To city fills the origin/destination time zone from
  `City.timezone` (and the origin/destination text when blank). Server side: on save, a blank zone with a
  city takes the city's zone (so it works without JS and in quick add); in the browser, the city options
  carry `data-tz` (a tagged select like `locations.widgets.CountryTaggedSelect`) and a small script fills the
  zone field only when it's blank. The zone field stays editable (airports in another zone than the city are
  rare but real); its help text changes to "Filled in from the city".
- `leg_quick_add` matches cities by name already: it also fills zones from them.
- **City selects everywhere on trips forms** (stay, leg from/to, day): two optgroups, **This trip** (the trip's
  cities) then **Everywhere else**, so every row behaves the same (today a blank extra row lists all cities
  while filled rows list only the trip's). Picking a city from Everywhere else adds it to `Trip.cities` on
  save (as `fill_day_cities` already does for stays). Choices still built once per page (`share_choices`).
- **Activity place:** picking a `poi` shows its city; nothing typed.
- Tests: zone filled from city on save when blank, not overwritten when set; quick add fills zones; optgroups
  present on blank and filled rows; a city from Everywhere else joins `Trip.cities`; query counts unchanged.

### E6 — Logistics tables become travel notes

- Day page: **+ Travel** is renamed **+ Travel notes** and moves next to Phase / Callout / Free text;
  **+ Logistics table** is removed from Add to this day. The travel section editor already has intro +
  reference rows (`TravelPayloadForm` extends the table form) and "Legs shown here".
- An existing `logistics_table` section keeps rendering and editing as now. Its section page offers
  **Turn into legs** (arrow rows, as now) and **Make it travel notes** (changes the type to `travel`; the
  payload is compatible; remaining rows become reference rows). `convert_travel_tables` and the trip-wide
  review are unchanged.
- `import_itinerary` unchanged (parsers emit `logistics_table`; `--apply` converts arrow rows as now).
- The booklet: confirm with the snapshot test; if a section type label it prints changes, review the diff and
  update the snapshot deliberately.
- Tests: Add to this day has Travel notes and no Logistics table; Make it travel notes keeps the rows;
  old tables still render.
- Help: `adding-a-day` (section types), any guide naming logistics tables; bump `updated`.

## Not changing

- The data model of stays, legs, confirmations, contacts and tasks (only `Trip.home_currency` is new).
- The trip page's layout and its query count (`QueryCountTests`), the booklet (snapshot), the calendar feed,
  the public view (`audit_public_leak` green), the admin.
- Who may do what: everything here is editors-only except reading (To do page, budget rates).

## After E6

Update the CLAUDE.md section "### Edit by day" status line, and the "Edit this day" bullet to say the day page
is where stays, legs, activities, meals, sections and to-dos are added.
