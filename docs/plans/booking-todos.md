# Plan: to-dos that cover several items, and a "To book" list you can work in

Status: not started. Decided by James and Claude 2026-10-28. Two phases, one branch each, in order: K1 (a to-do
covers several items), K2 (Reference's to-do and Not booked lists work like the days). Read with `CLAUDE.md` →
Trips → "Booking tasks point at their item", "Confirmations attach like comments", "Round trips", "The item panel",
"One page to read and edit", and `docs/plans/retire-decision-todos.md` (D2 is merged, so every to-do is a booking
to-do and `BookingTask.kind` is gone).

## Why

1. **A booking often covers more than one item, but a to-do points at one.** James's round-trip train: "Also add the
   return trip" makes two legs; the to-do "Set up train travel" can point at only one, so the other stays in **Not
   booked yet**. The same happens with a flight with a connection (PIT → ATL → FRA as two legs), a rail pass covering
   several journeys, or a hotel booked together with its airport transfer. Confirmations already solve this (one
   `Confirmation`, many `ConfirmationLink`s); to-dos should work the same way.
2. **Reference reads like a report, not like the days.** On a day, a click on a row opens it in the item panel and
   everything is editable there. In Reference, **Still to book** rows only jump to the item, a to-do can't be ticked
   off or edited without going to the To do page, and **Not booked yet** rows only jump; the two lists also show the
   same need twice in two shapes (an item with a to-do is in one list, without one in the other). And there's no way
   to say "this train needs no booking" (a walk-up regional train with an operator typed in stays in Not booked
   forever unless the operator is cleared).

## Decisions (2026-10-28)

1. **To-dos link like confirmations.** A new generic `TaskLink` (task + content type + id), any number per to-do,
   to legs, stays and trip activities (the kinds Not booked looks at). The three FKs and `bookingtask_one_item` go.
2. **A return trip shares the outbound's booking by default.** "Also add the return trip" gains **Same booking as
   the way out** (ticked when the outbound has an open to-do or a confirmation): the return is linked to the
   outbound's open to-dos and its confirmations. Unticked, it's independent as today. (CLAUDE.md's "not …
   confirmations" for the return changes to this rule.)
3. **Offered, never automatic** — as today: partner items are pre-ticked on forms, a confirmation reaching one
   covered item is offered to the others, never linked silently.
4. **Reference gets one "To book" list** (K2) instead of Still to book + Not booked yet, rows open in the panel, and a
   to-do can be ticked done in place. The To do and Bookings pages use the same rows.
5. **"No booking needed"** is a per-item flag on legs, stays and trip activities; such an item is never in Not
   booked / To book.

## K1 — A to-do covers several items (branch `k1-task-links`)

- **Model.** `TaskLink` (`task` FK → BookingTask, CASCADE, `related_name="links"`; `content_type`, `object_id`,
  `item` GenericForeignKey; unique task + content type + id; `db_table = "trip_task_links"`), `TaskLink.link(task,
  item)` checks the item's trip is the task's (like `ConfirmationLink.link`), once per pair. `models.TASKABLE` =
  leg / stay / activity. A `task_links` GenericRelation on `TransportLeg`, `Lodging` and `TripActivity` deletes the
  links with the item (as `confirmation_links` does).
- **Migrations** (three, because Postgres refuses index work after a data change in one transaction — see
  bucketlists 0003–0005): 0056 creates `TaskLink`; 0057 copies every `leg` / `stay` / `activity` FK into a link
  (reverse: the first link of each task back into its FK, the rest dropped, said in the docstring); 0058 removes
  `bookingtask_one_item` and the three FKs. Read every `RemoveField` and check with `sqlmigrate`. A migration test
  (`RestoringTransactionTestCase`, pinning `rewards`, `reviews` and any other app the CLAUDE.md testing rules list
  for stepping `trips` back) puts a to-do on each kind at 0056, migrates, and checks the links.
- **`booking_tasks.py`.** `attach` works from a `booking_tasks__links` prefetch (one more query on the trip page and
  the day fragment: pins 37 → 38 and 35 → 36, say so in `test_detail`; the To do and Bookings pages' counts likewise):
  `task.items` (in date order), `task.item` = the first (old templates keep working while they're converted),
  `task.item_day` = the first item's day, and every covered item gets the task in `open_tasks`. `task.cover_label`:
  "Augsburg → Munich and back" when the items are a leg and its reverse (ends swapped), "PIT → ATL → FRA" when legs
  chain on one date (each leg's destination is the next one's origin), else "Hotel Laimer Hof + 1 more". `not_booked`
  builds its "tasked" set from the links. `suggest` / `task_link` **add** a link (never replace); the dismissal line
  is unchanged. `offer_for` offers a task when any of its items is newly confirmed.
- **Partners** (`booking_tasks.partners(item, legs, stays, activities)`, pure): for a leg, its reverse leg on the
  trip (ends — city if set, else first word — swapped, a later date or the same date and later) and the legs chained
  to it on the same date; nothing for stays and activities. Used to pre-tick, never to link on its own.
- **Forms.** `BookingTaskForm`'s three "About" pickers become one **Covers** field: grouped checkboxes (Day N →
  its legs, stays checking in, activities; plus "Not on a day"), choices built once per trip object
  (`share_choices`, so the count doesn't grow with rows). `?leg=` / `?stay=` / `?activity=` may repeat and pre-tick;
  "Add a to-do for this" on an item's page (`_item_todos.html`) pre-ticks the item **and its partners**, with a line
  "Also ticked: Munich → Augsburg (the way back)". The `from_note` path keeps working (it passes its item the same
  way).
- **Return trip.** `LegEditForm`'s Return section gets **Same booking as the way out** (initial: the outbound has an
  open to-do or a confirmation). Ticked, saving the return links it to each of the outbound's open to-dos and
  confirmations (`TaskLink.link`, `ConfirmationLink.link`). Leg quick add and Pick-made legs are unchanged.
- **Confirmations.** When `item_confirmations` gives an item a confirmation and one of the item's open to-dos covers
  other items that have no confirmation, the page after saving offers **Also attach GCH7JS to: ☑ Munich → Augsburg**
  (ticked) before `task_offer`; `task_offer` then lists the to-dos all of whose items are now confirmed.
- **Showing it.** Still to book (until K2 replaces it), the To do page's `_task_row.html`, the item rows' "Still to
  book: …" (every covered item shows it), and the booklet's Still to book print `cover_label`; each covered item's
  anchor is reachable from the to-do (the label links to the first, "+ N more" lists the rest in a `title`). Update
  the booklet snapshot deliberately (`UPDATE_SNAPSHOTS=1`) and check the diff is only the "For:" lines.
- **History.** `changes.snapshot` stores the links of a removed item (`"task_links": [task_pk, …]`) and `restore`
  re-links to tasks that still exist; a pre-K1 snapshot's `"tasks"` list restores as links too. Adding / removing a
  link isn't a history line (as today: changing a task's FK wasn't).
- **Elsewhere.** The admin's `BookingTaskInline` shows a read-only "Covers" column; Your data export lists a to-do's
  covered items by label; the calendar feed and the public view don't use to-dos (check); `audit_public_leak` unchanged.
- **Tests.** Links copied by the migration; one to-do on two legs empties Not booked for both; `cover_label` for
  round trip / chain / other; partners (reverse, chain, none for stays); the form pre-ticks partners; Same booking as
  the way out links the return to to-dos and confirmations, unticked links nothing; the confirmation offer; `offer_for`
  only when every item is confirmed; deleting a leg deletes its links but not the to-do; restore re-links; pins.
- **Help.** `bookings-and-confirmations`: a to-do can cover a round trip or a connection, how to tick the other legs,
  Same booking as the way out; bump `updated`.

## K2 — "To book" you can work in (branch `k2-to-book`)

- **One list in Reference** (`#to-book`; the old `#still-to-book` and `#not-booked` anchors map to it in the hash
  script, as `#overview` does): `booking_tasks.to_book(trip)` (no queries, after `attach` and the confirmations)
  returns rows in date order:
  - an item with no confirmation that isn't marked "No booking needed" and is bookable (Not booked's rule) **or** has
    an open to-do: what, label, day, and its state — **No plan yet** (amber) or the to-do(s) "Book trains · High ·
    due Aug 1" (one row per item group: a to-do covering a round trip is one row "Augsburg → Munich and back");
  - then **Other to-dos**: open to-dos covering nothing (with their Day N if set).
  Needs attention's "N not booked" and "N to do" become "N to book" (items) and "N other to-dos"; the day summary's ⚠
  keeps counting the same things.
- **Rows behave like the days' rows.** A row carries `data-panel`: a to-do row opens `task_edit` (editors) or the
  to-do read-only (`item_panel` gains kind `task`), an item row with no plan opens the item's own page. Editors get,
  on each row: **Mark done** (to-do rows; `task_done` answers 204 to `fetch`, the row greys and moves to a "Done
  today" fold until reload), and on No-plan rows **Add a to-do** (opens `task_new?leg=…` in the panel, partners
  pre-ticked) · **Add confirmation** (`item_confirmations` in the panel) · **No booking needed**. Comments on to-dos
  stay as they are.
- **Refreshing.** After a save in the panel from a Reference row, `panel.js` swaps the list for
  `trips:to_book_fragment` (`/trips/<pk>/to-book/fragment/`, the Reference list alone from `_trip_page_context`, like
  `day_fragment`; pin it at the page's count) as well as the item's day; a to-do saved from a day's item does the
  same. Without JavaScript every link is a normal link with `next` back to `#to-book`.
- **"No booking needed".** `no_booking` BooleanField (default False) on `TransportLeg`, `Lodging`, `TripActivity`
  (one migration; `sqlmigrate`). On each item's form (Details section, "No booking needed — e.g. a walk-up train"),
  set also by the row's button (`trips:item_no_booking`, POST, editors, `kind` / `id`, `undo=1`). The item's row shows
  a quiet "no booking needed" where the stage badge would say planned/scheduled; `not_booked`, `to_book`, the ⚠ count
  and the booklet's Not booked list skip it. Tracked in `changes.TRACKED` for the three kinds.
- **The other pages.** The To do page: open to-dos by priority / due as now, but its Not booked section is the same
  `to_book` rows (with the quick actions); Bookings' Not booked yet uses them too (read-only rows open on the trip
  page with `?item=` as today, actions only on the trip page and To do). One partial, `partials/_to_book.html`, for all
  three.
- **Booklet.** Unchanged except the "No booking needed" items leave its Not booked list — update the snapshot only if
  the fixture has one (add one leg with `no_booking` to the fixture so it's covered, and check the diff).
- **Tests.** `to_book` rows (no plan / to-do / round trip as one row / other to-dos / confirmed gone / no_booking
  gone); Mark done by fetch (204) and by form; the fragment's query pin; `data-panel` on rows; the quick actions'
  URLs; the hash mapping; `no_booking` hides an item everywhere it should and the form saves it; help links.
- **Help.** `reading-your-trip` (Reference → To book) and `bookings-and-confirmations` (No booking needed, working
  from To book); bump `updated`.

## Not changing

- Confirmations, their files and Reference → Confirmations.
- Catalogue-note "book ahead" warnings and their "Add as a to-do" (they pass their item through the same pre-tick).
- Choices: a to-do is still never a decision.
