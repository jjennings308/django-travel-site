# Plan: retire decision to-dos (the old way of choosing)

Status: D1 done (2026-10-28, branch `d1-decisions-to-choices`); D2 done (2026-10-28, branch `d2-remove-decision-todos`; `convert_day_first` deleted: nothing on the import path used it). Decided by James and Claude 2026-10-28. Two phases, one branch each, in order:
D1 (stop making them, convert or merge the ones left), D2 (remove them from the code). Read with `CLAUDE.md` →
Trips → "Decisions are tasks with options", "'Choose one' groups and votes", "Typed choices", and
`docs/plans/retire-old-section-types.md` (the same two-step pattern).

## Why

A choice used to be a to-do with options (`BookingTask.kind = decide` + `TaskOption`, trip-page UX U6). Day-first P4
replaced it with "choose one" groups on the day, and typed choices (T1–T3) made Pick create the real item. The old
way is still reachable — **Add options** under every to-do in Reference → Still to book and on the to-do rows,
**Make it a decision…** on the to-do page — so trips end up with both: a "Decide: …" to-do in Still to book and a
choice on the day, unlinked. Converting today always makes a *new* group, so a trip that already has the choice
gets a duplicate.

## Decisions (2026-10-28)

1. **No new decision to-dos.** Every entry point goes in D1.
2. **Converting merges when the choice already exists.** If the to-do's day has an open choice that looks like the
   same decision, the options join it instead of making a second one.
3. **A converted to-do stays as the booking to-do by default.** Old decision to-dos are really "book the hotel"
   reminders with a priority and due date; converting turns them into a plain **book** to-do (options moved to the
   choice, a "Options moved to the choice “…” on Day N" line in its notes). A tick-box "Tick it off instead" does what
   conversion does today.
4. **Nothing is lost in D2.** Options still on to-dos when D2's migration runs (closed or done ones) are written into
   the to-do's notes ("Options considered: A; B (chosen); C") before the table goes.

## D1 — Stop making them; convert or merge what's left (branch `d1-decisions-to-choices`)

- **Entry points:** remove **Add options** / **Options (n)** from Reference → Still to book and from
  `partials/_task_row.html`, and **Make it a decision…** from `task_form.html`. An open to-do that *has* options shows
  instead **Make it a choice** (editors) → the one-to-do conversion below. `task_options` stays reachable only by URL
  until D2 (read-only is fine).
- **Matching an existing choice** (`day_first.match_group(task, day, groups)`, pure): an open group on the conversion's
  day (its own day, else its item's, else none — never Day 1 when matching) is a match when its prompt and the task's
  title share a significant word (ignoring "which / where / pick / choose / book / the / to / in / stay / hotel"
  stop-words, accents and case, `catalogue_links.match_keys`-style), **or** at least one option title matches one of the
  task's option titles. More than one match → none (ask). `plan()` gives each conversion `target` = the matched group
  or None.
- **Merge** (`apply`): options whose title isn't already in the group are added (title, detail → notes, url, est_cost +
  currency; a chosen task option picks that option only when the group is still open and nothing else is chosen — else
  its title goes into the group's notes as "Earlier choice: …"); the group's kind is untouched. **New group** when no
  target, as today. Then the task: **book** kind, its `TaskOption`s deleted, the "moved to" line in its notes, still open
  — or done if "Tick it off instead" was ticked (page) / `--tick-off` (command).
- **Review page** `trips:trip_convert`: each row says **Merge into “Where to stay in Augsburg” (Day 4)** or **New choice
  on Day 4**, with a select to switch (the day's open groups, or "New choice"), plus the Tick-it-off box. **Make it a
  choice** on a single to-do opens this page with only that row.
- **Command** `convert_day_first --trip <pk> | --all [--apply] [--tick-off]`: the dry run prints Merge / New per to-do;
  ambiguous matches are listed and skipped (do those on the page).
- **Banner:** "N decisions to turn into choices" stays until none are left; the "decisions" count in Needs attention
  counts only open choices plus open decision to-dos (unchanged until D2).
- **Tests:** match rules (word overlap, option overlap, stop-words, two matches → none, never Day 1); merge adds only
  missing options and respects an existing pick; default keeps the to-do open as book with its notes line; tick-off;
  dry run vs apply; no entry point renders **Add options** / **Make it a decision…**; query counts unchanged.
- **Help:** `options-and-votes` and `bookings-and-confirmations` — choices live on the day; to-dos are for booking;
  bump `updated`.
- **James runs it:** on dev `convert_day_first --all` (dry run), fix the ambiguous ones on the page, then on
  production `pg_dump` and `convert_day_first --all --apply`.

## D2 — Remove the old way (branch `d2-remove-decision-todos`; merge only after D1 has run on production)

- **Migration:** refuses with a clear message while any **open** to-do still has options ("run `convert_day_first --all
  --apply` first: trips …"). For the rest, appends "Options considered: …" (chosen marked) to the to-do's notes, then
  drops `TaskOption` (`taskoption_one_chosen` goes with it) and `BookingTask.kind` (every to-do is a booking to-do).
  Check with `sqlmigrate`; read every `RemoveField` / `DeleteModel`.
- **Code:** delete `task_options`, `option_add` and their URLs and templates, `TaskOptionForm` / `TaskOptionFormSet`,
  the `?from_option=` pre-fill on the new-stay / new-activity pages, `BookingTaskForm`'s kind handling, the decision
  half of `day_first` (`plan` / `apply` / `_from_task` / `pending_count`), `trips:trip_convert` and
  `convert_day_first` (or keep the command only if the import path still needs it — say which), the banner's
  "decisions to turn into choices", `views.open_decisions` (the banner's "N decisions" = open choices only), the
  "Decide:" prefix and options list in Reference and the booklet, `currencies.py`'s TaskOption row, the trip page's
  `booking_tasks__options` prefetch (query pin 38 → 37, fragment 36 → 35; say so in `test_detail`), and TaskOption
  in the admin, `changes` (a pre-D2 removal snapshot with options restores the to-do without them) and the Your data
  export.
- **Booklet:** the "Decide:" line goes — update the snapshot deliberately (`UPDATE_SNAPSHOTS=1`) and check the diff
  is only that.
- **Tests:** delete `test_decisions.py`'s option tests; switch fixtures that make decision to-dos (`test_day_first`,
  `test_todo_page`, `test_tidy`, `test_option_groups`, the booklet fixture) to choices or plain to-dos; add the
  migration's refuse / notes tests (`RestoringTransactionTestCase`).
- **Docs:** CLAUDE.md (remove the "Decisions are tasks with options" bullet and the decision parts of "Choose one",
  update the pin), help guides; bump `updated`.
- Full suite in parallel; `makemigrations --check`; `check_layers.py`; `audit_public_leak` exits 0.
