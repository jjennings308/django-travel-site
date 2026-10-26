# Plan: notes on catalogue places, activities and events that flow into trips

Status: N1 done (2026-10-26, branch `n1-catalogue-notes`; reports reuse the `content_reported` notification rather than a report model); N2 done (2026-10-26, branch `n2-notes-on-trips`; the trip page shows "From <place>" as text, not a link, so the query count only grows by one; a trip with no catalogue links makes no extra query); N3 done (2026-10-26, branch `n3-note-warnings`; "Add as a to-do" opens the to-do page pre-filled rather than creating it, and the booklet prints the warnings too); N4 done (2026-10-26, branch `n4-events-on-trips`; suggestions are offered for sections, not trip activities; `On trips` counts don't include events — ask if wanted); N5 not started. Decisions answered by James 2026-10-26 (below). Phases N1–N5, one branch
each, in order. Read with `CLAUDE.md` → Dependency layers, "Approval / moderation", "Trip items linked to the
catalogue" (R18), "The booklet is snapshot-guarded", "The detail page holds a fixed query count" and "Tidy
suggestions" (U7).

## Why

A trip's tips are mostly about the places in it, and every trip that goes there needs them again: Arches
needs a timed entry booked ahead, a restaurant is closed on Mondays and Tuesdays, Marburg Castle's museum is
cash only. Today they're typed into each trip as callout sections (Europe 2027 has 15; about half are about a
place — Marburg Castle, the Documentation Center, the Beatles Story, Leeds Castle, Hampton Court, LHR Terminal
3 — and none is linked to the catalogue). Written once on the place, activity or event, a note should show up
on every trip that includes it, on the web page and in the PDF, and the facts that matter for planning (closed
days, how far ahead to book) should warn the traveller instead of waiting to be read.

## Decisions (James, 2026-10-26)

1. **Members add notes, staff approve** (staff publish directly), like submitted events. Notes show on public
   catalogue pages, so they're moderated.
2. **Structured parts:** a note can say which **weekdays the place is closed** and **how far ahead to book**
   (with a booking link). These drive warnings on trips; plain notes need neither.
3. **Hide per trip:** an editor can mark a catalogue note "Not for this trip"; it stays in the catalogue and on
   other trips.
4. **Existing trip callouts** about a linked place get a tidy suggestion to move them to the catalogue — never
   automatic.

## The model (N1)

A new app `apps/catalogue_notes` (label `catalogue_notes`), **layer 3, after `events`**: it may import
`locations`, `activities` and `events` (add it to the layer table, `LAYERS` / `SAME_LAYER_ALLOWED` in
`scripts/check_layers.py` and `docs/architecture/app_dependencies.md`), and `trips` (layer 4) may read it. The
catalogue apps never import it: their pages show notes through a shell partial (`{% url … as %}`), as reviews do.

`CatalogueNote` (`Approvable`, `created_by` SET_NULL, timestamps, `db_table` set):

| Field | |
|---|---|
| `poi` / `activity` / `event` | exactly one (check constraint, like `bookingtask_one_item`) |
| `tone` | tip / warning / critical (the trip's callout tones) |
| `text` | the note itself ("Cash only; no ATM near the castle.") |
| `closed_weekdays` | optional list of weekdays (0 = Monday), e.g. Mon + Tue |
| `book_ahead` + `book_ahead_unit` | optional lead time: 3 + months, 2 + weeks, 10 + days |
| `booking_url` | optional link for the booking ("recreation.gov timed entry") |
| `checked_on` | date last confirmed (defaults to today on save by staff); shown as "checked Oct 2026" |
| `order` | |

**What an item shows** (`catalogue_notes.services.notes_for`): an event's own notes, then its activity's, then
its venue's (`Event.poi`); an activity's own, then its venue's (`Activity.venue`); a place's own. Approved only,
plus the reader's own pending ones on catalogue pages.

## Phases

### N1 — Notes on catalogue pages

- The app, model and migrations (with an approval-queue row "Catalogue notes", seeded like events 0003; the
  `submission_received` / `submission_reviewed` notifications come from `Approvable`).
- Forms: `CatalogueNoteForm` (tone, text, closed weekdays as day checkboxes, book-ahead number + unit,
  booking link, checked on). Members' notes are pending until approved; staff's are published.
- Pages: `catalogue_notes:for_target` (the list, loaded after the place / activity / event page by the shell
  partial `partials/_catalogue_notes.html` — no query on the page itself) and `catalogue_notes:add` /
  `edit` / `delete` (creator until approved, staff always). On place, activity and event pages: a **Good to
  know** card with each note (tone, text, "Closed Mon, Tue", "Book 3 months ahead" + link, "checked Oct 2026")
  and **Add a note**.
- Report a note → staff (as reviews); the staff dashboard lists pending notes with the other approvals.
- CSV import/export: a `note` kind is **not** in N1 (later, if wanted).
- Tests: create pending / staff published; visibility (public sees approved; creator sees own pending; 404
  otherwise); one target only; inheritance order; layer check.
- Help: a new guide section in `places-and-events` ("Good to know notes"); bump `updated`.

### N2 — Notes on the trip (web and PDF)

- Which trip items reach the catalogue today: `Meal.poi`, `TripActivity.poi`, `Section.poi` / `Section.activity`
  (R18). For each, its notes (`notes_for`) show **under the item on its day**: the meal row, the activity row, the
  section — styled like the trip's callouts, marked "From <place>" and "checked Oct 2026". The same place used
  twice on a trip shows its notes on each item.
- Loaded with the trip page's prefetch in a fixed number of queries (notes for every target in one query):
  `QueryCountTests` re-pinned at the new number (expected +1 or +2) and the reason written in CLAUDE.md.
- **Not for this trip** (editors): `trips.TripHiddenNote` (trip, note; unique) — hides it on this trip's page and
  booklet; a "Show N hidden notes" link brings them back. Never in the public view.
- The booklet prints them under the same items (`pdf/booklet.html`): a deliberate snapshot update, reviewed.
- Tests: notes show under the linked item and in the booklet; hidden ones don't; a note on an activity reaches a
  section linked to that activity and to an event of it; viewer sees them, can't hide; query pin.
- Help: `reading-your-trip` (where the notes come from), `adding-a-day` (link a meal/section to the catalogue to
  get its notes).

### N3 — Warnings from closed days and booking lead times

- **Closed:** a meal (with a reserved time or on its day) or an activity on a weekday its place is closed →
  "⚠ Closed on Mondays" on the item, counted in the day's ⚠ and in the Needs attention banner ("2 closed
  days").
- **Book ahead:** a note with a lead time gives "Book by Jul 1" (the item's day minus the lead time) on the item;
  the banner counts those due within 30 days or overdue ("1 to book ahead"); **Add as a to-do** creates a
  `BookingTask` about the item with `due` = the book-by date and the booking link in its notes (offered, never
  automatic; once added, the item's to-do covers it and the warning goes quiet).
- All derived in `itinerary.py` from what N2 loaded (no new queries); `itinerary.overview` adds them to
  `day.attention`.
- Tests: Monday meal at a Mon-closed place warns, Wednesday doesn't; book-by date and the 30-day window; Add as a
  to-do pre-fills; a to-do about the item silences the warning; hidden notes don't warn.
- Help: `reading-your-trip` (the warnings), `bookings-and-confirmations` (to-dos from notes).

### N4 — Events on trips

- Trip items can point at a place or an activity but not an **event**, so an Oktoberfest 2027 day can't get the
  event's notes. Add `TripActivity.event` and `Section.event` (optional, SET_NULL; choices: visible events whose
  dates overlap the trip, in its cities first — `events_for` style), on the activity form and the section page.
- `catalogue_links` suggestions learn events (an unlinked activity / section whose name matches one event of
  those dates: "Looks like Oktoberfest 2027 — Link / Not this one").
- The trip page shows the link (`partials/_catalogue_link.html`); `catalogue_counts` counts events too if wanted
  (ask).
- Tests: choices limited to overlapping events; suggestion and dismissal; notes inherited through the event.

### N5 — Move a trip's callouts to the catalogue

- A new tidy kind `catalogue_note` (`apps/trips/tidy.py`, pure): a **callout** section on a day whose text names
  a place / activity / event that a meal, activity or section **of that day** is linked to → "This looks like a
  note about Marburg Castle — Move it to the catalogue". Review page only (never `tidy_trip --apply`).
- Applying it creates a **pending** `CatalogueNote` on that target (tone from the callout, text from it, created
  by the editor) and deletes the callout section — the note shows on the trip again once approved, and staff are
  notified as for any submission. Applied by staff, it's published at once.
- Tests: suggested only for a linked target named in the text; apply creates the pending note and removes the
  section; a stale suggestion is skipped; dismissal.
- Help: `tidying-an-itinerary` (the new suggestion).

## Not changing

- Trip callout sections stay: notes about this trip only ("Olga is arranged by John", "Day 3 is a travel day by
  design") are still callouts.
- The public trip view (never shows notes), the calendar feed, Reference.
- Cities and regions don't get notes in this plan (a later phase could add "Shops close on Sundays in Bavaria").

## After N5

Update CLAUDE.md (a "Catalogue notes" bullet under Approval / moderation and one under Trips) and this file's
status line.
