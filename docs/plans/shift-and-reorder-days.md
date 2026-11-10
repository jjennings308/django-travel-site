# Plan: move the whole trip to new dates, and put days in a new order

Status: DR1, DR2, DR3 and DR4 done. DR4 (2026-11-09) on branch `dr4-add-days`. DR3 (2026-11-02) on branch `dr3-day-move-fixes`. DR1 (2026-11-02) on branch `dr1-shift-trip`; DR2 (2026-11-02) on branch `dr2-reorder-days`. Asked for by James 2026-11-02 (Europe 2027 / Bavaria: the start moves from 9/17 to 9/10 and
some days need to swap round). Two phases, one branch each, in order: DR1 (shift the trip by N days), DR2 (reorder
days). Read with `CLAUDE.md` → Trips → "One page to read and edit; trip-wide pages are views; Settings holds
trip-level things" (the fit-the-days page, `apps/trips/day_fit.py`), "Leg times", "Planned legs", "Change digest",
"History and undo", "Booking tasks cover their items", "Catalogue notes on a trip" (warnings) and "Trip items linked
to the catalogue" (events).

## Why

Every day, journey and stay carries its own date. `day_number` is only the count in date order. So:

- **Moving the start date doesn't move the trip.** Settings saves the new dates, then the fit-the-days page
  (`day_fit.plan` / `apply`) makes **empty** days for 9/10–9/16, renumbers by date (the old Day 1 on 9/17 becomes
  Day 8) and offers to **delete** the days now past the end, with their meals, notes, activities and choices. Legs
  and stays keep their old dates. Moving a trip by a week means retyping it.
- **There is no way to change the order of days.** To swap Day 3 and Day 6 you change every journey's date, every
  stay's check-in and check-out, and move the meals, notes, activities and choices by hand. (`Day` is unique on
  trip + `day_number`, not on date, which helps: the contents hang off the `Day` row.)

## Decisions (James and Claude, 2026-11-02)

1. **A day's contents travel with the day.** Its city, theme, meals included, roster, meals, notes, activities,
   choices, comments and links are on (or hang off) the `Day` row, so moving a day means giving the row a new date.
   Journeys are tied by **date**, so they get the day's new date. Local wall-clock times are kept (a 10:15 train is
   still 10:15, recomputed to UTC in each end's zone, so a DST change between the two dates is right).
2. **Shift (DR1) moves everything** by the same number of days: the trip's start and end, every day, every journey
   (date and times) and every stay (check-in and check-out). The length doesn't change. To change the length as
   well, shift first, then change the end date in Settings (the fit-the-days page as today).
3. **What doesn't move:**
   - payments (`TripExpense.spent_on`) and confirmations' `booked_on` (they happened when they happened);
   - catalogue events (Oktoberfest's dates are Oktoberfest's);
   - **to-do due dates**, unless **Also move to-do due dates** is ticked (off by default: a due date is usually a
     booking deadline, which doesn't move because the trip did).
4. **Booked things are moved on the site, never at the provider.** The preview lists every journey and stay with a
   confirmation ("Hotel Laimer Hof · GCH7JS · booked for Sep 17–21"). **Add a to-do to change each booking** is
   ticked by default: one to-do "Change booking <number> to the new dates", covering that booking's items
   (`TaskLink`), priority High.
5. **Preview first, then apply.** Nothing changes until Apply; one transaction; one history line; and one **Undo**
   on that line while nothing else on the trip has changed since.
6. **Reorder (DR2) keeps the dates where they are and moves the days between them.** The new order gets the trip's
   dates in turn. A stay moves with its nights only when they stay together and in order; otherwise it stays and is
   listed.

## DR1 — Shift the trip (branch `dr1-shift-trip`)

- **`apps/trips/reschedule.py`** (new; pure planning plus one `apply`):
  - `shift_plan(trip, days)` (`days` = N, may be negative) → what moves: trip dates; days (old → new date); legs
    (old → new date, and local departure / arrival when timed); stays (old → new nights); to-dos with a due date;
    plus the warnings:
    - **booked** items (a confirmation covers them);
    - **events**: items linked to an event (`TripActivity.event`, `Section.event`) whose new day falls outside the
      event's dates ("Hacker-Festzelt is linked to Oktoberfest 2027, Sep 18–Oct 3; Day 2 will be Sep 11");
    - **closed days**: catalogue-note closed weekdays newly hit (reuse `itinerary.note_warnings`'s rule on the new
      dates; list only the new ones);
    - legs on a date that is no day of the trip (they move too; still flagged).
  - `shift(trip, days, user, move_due=False, booking_todos=True)`: one transaction inside
    `changes.batch("Moved the trip by N days: Sep 17–29 → Sep 10–22")`.
    - Day dates first. No constraint fights: numbers don't change.
    - Legs through `TransportLeg`'s own helpers: local time in its zone + N days → UTC. Planned legs get the date
      only. `save()` sets `date` from the local departure as today.
    - Stays, the trip's dates, then the optional due dates and the booking to-dos.
    - The urgent leg notification (`URGENT_DAYS`) is **not** sent per leg during a shift. The digest carries the
      one batch line. If any leg now departs within `URGENT_DAYS`, send one "the trip has moved" notice instead.
    - Before it changes anything, store `{"days": {pk: old}, "legs": {pk: [old date, old departure_at, old
      arrival_at]}, "stays": {pk: [in, out]}, "trip": [start, end], "tasks": {pk: old due}, "made_tasks": [pk, …]}`
      in the batch line's `TripChange.before`.
  - `undo_shift(change)` restores those values and deletes the booking to-dos it made (unless they've been edited or
    done since; those stay and are said). Offered only while the line is the trip's newest change
    (`changes.latest_change_ids` rule).
- **Where it starts:**
  - **Settings → The trip** gets **Move the whole trip…** (editors) → `trips:trip_shift` (`/trips/<pk>/shift/`): a
    new start date (the end is shown, computed), **Preview** → the lists above with the two ticks → **Apply** →
    back to the trip page with "Moved the trip to Sep 10–22. 2 bookings to change: see To book."
  - **The fit-the-days page** catches the case that started this. When Settings saved a new start date and the
    days are now outside the dates, the page heads with "Your days are still on Sep 17–29. **Move everything to
    start on Sep 10** instead?" It links to `trip_shift` with the old start date and the new one, so N is known.
    `trip_settings` passes the old start as `?moved_from=YYYY-MM-DD` when the start changed.
    - In that case `trip_shift` moves the **contents only**. The trip's dates are already saved, and if the end
      date was also changed by a different amount, the fit-the-days page runs after the shift for whatever is
      still missing or outside.
- **Tests** (`tests/test_reschedule.py`):
  - every kind moves by N (forwards and backwards); local wall-clock times kept across a DST change (a CEST →
    CET example);
  - a planned leg moves its date only;
  - payments, `booked_on`, events and due dates untouched (and due dates moved when ticked);
  - the booking to-dos cover the right items, one per confirmation;
  - the warnings (booked, event outside its dates, closed day, stray leg);
  - one history line; Undo restores everything and refuses once something else changed; no urgent notice per leg;
  - the fit-the-days page offers the shift after a start-date change;
  - editors only (403 / 404 as usual); the trip page's pins unchanged (nothing new on it).
- **Help:** `starting-a-trip` or `adding-a-day` (whichever has the dates section): "Moving the whole trip"; bump
  `updated`. `trip-history`: the Undo on a move.

## DR2 — Put days in a new order (branch `dr2-reorder-days`)

- **Page:** `trips:trip_reorder` (`/trips/<pk>/reorder/`, editors). Linked from Days (`#days`) on the trip page
  ("Reorder", next to Expand all), Settings' Days, and **Move this day…** on the day page (that day highlighted).
  - The days show as their folded lines: the same line 1 and `.day-glance` as the trip page, from
    `itinerary.overview` / `attach_stays` (one partial shared with `partials/_day.html`'s `<summary>`).
  - The date column stays still: the slots are Sep 10, Sep 11, …. Only the day lines move between them, so you see
    "Munich — Oktoberfest" land on Sep 13.
  - Moving uses **↑ / ↓** buttons on every row (also the phone way), plus drag with HTML5 drag-and-drop in Alpine.
    No new CDN file.
  - Without JavaScript, each row has a "Position" number box.
  - **Preview** (the posted order, nothing saved) shows the new order, what moved, and the warnings. **Apply** saves
    it.
- **`reschedule.reorder_plan(trip, order)`** (`order` = day pks in their new order, every day once) and
  **`reorder(trip, order, user, booking_todos=True)`**:
  - Each day in `order` gets the n-th date of the trip's days (the dates, sorted, are the slots; a day count that
    doesn't match the dates is refused with "fit the days first").
  - Its legs get its new date (wall-clock kept, as DR1).
  - Then `day_fit.renumber`, done in two steps: first every `day_number` + 1000, then the final numbers, all in the
    same transaction, so `unique_day_number_per_trip` never fights.
  - **Stays:** a stay moves when the days of all its nights moved together, are still next to each other and are
    still in the same order. Its check-in becomes the first one's new date and its length is unchanged. Any other
    stay is left where it is and listed: "Hotel Laimer Hof (Sep 17–21) now covers Day 3 Füssen and Day 4 Munich:
    check it." Placeholder stays from the route builder follow the same rule.
  - Warnings as DR1 (booked items moved, events, new closed days), plus **text that names a day**: Tidy's
    `day_slip` rule run over the new order ("a note on Day 5 says 'Day 3'"), listed only.
  - Booking to-dos as DR1 (ticked by default) for booked items that moved.
  - History: one batch line "Reordered days: Sep 10 Augsburg, Sep 11 Munich, …". Its `before` holds the old date
    of each day, leg and stay, and Undo works as DR1 (newest change only).
- **Not in scope:** dragging days on the trip page itself. The trip page's days are live and open into the panel,
  and a stray drag on a phone would move a day. The reorder page with Preview and Undo is the safe place, one click
  away.
- **Tests:**
  - a swap and a three-way rotation: contents (meals, notes, activities, choices, comments, city, theme, roster)
    move with their days;
  - legs follow their days, wall-clock kept;
  - a three-night stay moved intact; a stay split by the new order is left alone and listed;
  - numbers renumbered without a constraint error;
  - the booking to-dos; the warnings, including a `day_slip`;
  - a mismatched day count refused;
  - Undo; the no-JS position boxes;
  - the page's query count fixed per page (pin it); the trip page's pins unchanged apart from the Reorder link (no
    query).
- **Help:** `adding-a-day` (or `reading-your-trip`, wherever days are explained): "Changing the order of days", the
    stay rule, Undo; bump `updated`.

## DR3 — Fixes after first use (branch `dr3-day-move-fixes`)

James used DR1/DR2 on Europe 2027 on 2026-11-02 (flipping the trip: UK first, then Germany, starting 9/10) and hit
these. Decided 2026-11-02.

**What James expected, and the rule to make true:** "moving a day moves everything on it". Meals, notes, activities
and choices already hang off the `Day` row. Journeys and stays don't: they carry their own dates. The fixes below
make every way of moving a day also move the journeys on its date, and handle stays explicitly. Don't add a `day` FK
to legs or stays (a stay spans several days, a leg can be overnight); keep the date rule and move them alongside.

1. **Changing a day's date by hand moves its journeys too.** Today `DayForm` (the day page and Settings' Days) lets
   anyone retype `date` (and `day_number`). Doing so moved only the day's own contents and left its journeys and
   stays on the old date, which is what scattered Day 2's hotels. New rule, in `DayForm` / `day_edit`:
   - `day_number` is no longer on the form. Numbers always come from `day_fit.renumber` (by date) after any date
     change.
   - A new date that another day of the trip already has is refused: "Sep 18 is Day 9 (Butzbach). To swap days, use
     Reorder days." Link `trips:trip_reorder?day=<pk>`.
   - A new date outside the trip's dates is refused with a pointer to Settings → Move the whole trip / the dates.
   - Otherwise the save goes through `reschedule.move_day(day, new_date, user)`. It moves the day, its journeys by
     wall clock (as DR2), and the stays whose nights are all on this day (a one-night stay checking in that day).
     Then `renumber` runs, and longer stays touching the day are listed in the message ("Hotel Laimer Hof Sep
     18–21 wasn't moved: check it"). All of it is one history line, undone by `undo_move`, with
     `before["reorder"]`'s shape so the existing undo works.
2. **Stays a reorder leaves behind get an offer, not just a warning.** In `reorder_plan`, for each entry of
   `kept_stays`, work out a suggestion: follow the days that held its nights. If those days are still consecutive
   after the reorder, check-in = the first one's new date and the length is kept. Otherwise, if most of its nights'
   days share one city and those days are consecutive now, use that run. Otherwise, no suggestion.
   - The preview shows each suggestion as a ticked box: "Move Hard Days Night Hotel to Sep 11–14 (with Liverpool's
     days)". Stays with no suggestion stay listed as today.
   - `reorder(…, move_stays=[pk, …])` applies the ticked ones inside the same transaction and history line, so Undo
     covers them.
   - The same suggestion is used for item 1's listed stays.
3. **The start-date offer appears whenever the start date changes.** `trip_days_fit` shows "Move everything to
   start on Sep 10 instead?" only when some day falls outside the new dates. So moving the start earlier and
   leaving the end alone (what James did first) never offered it. Show the offer whenever `moved_from` differs from
   the new start and at least one day still sits on its old date (i.e. the days don't already start on the new
   start date).
   - Also: when Settings changes **only** the start date, keep the length by default and say so. The fit page heads
     with "You moved the start to Sep 10. Move the whole trip (keeps 17 days, ends Sep 26) or keep the end at Oct 3
     (adds 7 empty days)?". The first choice is the shift, the second is today's add/remove list.
4. **"Change booking" to-dos know when they're not needed.** When `_booking_todos` makes one, it stores each
   covered item's booked dates on the to-do in a hidden notes line, like `FROM_NOTE` (`BOOKED_FOR`: `leg-12
   2027-09-18; stay-15 2027-09-18/2027-09-20`), hidden by `visible_notes`.
   - `booking_tasks.attach` marks such a to-do `back_on_booked_dates` when every covered item's date(s) equal the
     stored ones again. To book / the To do page then show "Back on its booked dates" and **Close this to-do** (Mark
     done). Offered, never automatic.
   - Undo of a move already deletes untouched made to-dos. This covers the case where the items were moved back by
     hand.
5. **Wording on booked items.** The "Still to book: <to-do>" line on a leg row, stay card and activity row reads
   **"To do: …"** when the item already has a confirmation. Keep "Still to book" for unbooked items. The booklet's
   section is unchanged (snapshot holds).
6. **Help:** `adding-a-day` / `reading-your-trip` (wherever DR1/DR2 were documented). Explain what moves with a day:
   its contents, its journeys and one-night stays; longer stays are offered. Also explain that a day's date can't
   take another day's date (use Reorder), and cover the start-date choice. Bump `updated`.

**Tests** (`test_reschedule`, `test_reorder`, plus the day form's tests):
- changing a day's date moves its journeys (wall clock) and its one-night stay, renumbers, lists a longer stay, and
  is one undoable line;
- refused for a date another day has (message names the day and links Reorder) and for a date outside the trip;
- `day_number` is gone from the form and Settings' Days still renders;
- the reorder suggestion for a split stay (consecutive again; by city run; none), applied when ticked, skipped when
  not, and undone with the rest;
- the fit page offers the move after an earlier-start-only change (James's case) and after a start+end change, and
  the start-only "keep length" choice;
- `BOOKED_FOR` stored and hidden; `back_on_booked_dates` true when moved back, false otherwise; Close works;
- "To do:" vs "Still to book:" wording;
- the trip page's and day fragment's query pins unchanged.

## DR4 — Add days at the start or end (branch `dr4-add-days`)

James's case (2026-11-09): "being able to handle adding a day(s) at the beginning or end that would not necessarily
change already confirmed things". A whole-trip move is the wrong tool for that: it moves every day and booking. So
this is a separate, smaller action:

- **`reschedule.extend_plan(trip, n, at)`** (pure preview, `at` = `"start"` / `"end"`): the trip's range grows on
  that side, the new dates get empty days, existing days keep their dates and contents. Days are numbered by date
  (`day_fit.renumber`), so adding at the start shifts the numbers; the preview lists the changes.
- **`reschedule.extend(trip, n, at, user)`**: one transaction under one history line "Added 2 days at the start:
  Sep 15–16". It creates only dates that have no day (a day kept outside the dates is used as it is). No booking
  to-dos, no notifications: nothing that was booked has moved.
- **Undo** (`undo_move`, since `is_move` accepts `before["extend"]`): deletes the days the line made, refusing when
  one has meals, sections, activities or choices on it, or a journey or stay now on one of their dates, then puts
  the trip's dates back and renumbers.
- **Page `trips:trip_extend`** (`/trips/<pk>/extend/`, editors; linked from Settings under the dates and offered on
  the fit-the-days page): number (1–60) + start/end → Preview → Add the days; returns to Settings' days table.
- Help: `starting-a-trip` → "Adding days at the start or end". The whole-trip move keeps its booking to-dos; its
  "keep booked items where they are" option stays a later, separate change.

**Tests:** `apps/trips/tests/test_extend.py` (previews, guards, apply leaves every existing day/journey/stay/booking
where it was, one line, undo and its refusals, the page's permissions and links).

## Not changing

- The fit-the-days page's own add / remove behaviour (DR1 only adds the offer at its top).
- Route builder, + Add, the item panel, the booklet layout (it just shows the new dates).
- The public view and calendar feed: they read the moved dates, nothing else.
