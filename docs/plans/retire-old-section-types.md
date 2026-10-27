# Plan: retire phases, callouts, free text and choose-your-adventure sections

Status: planning only (2026-10-27). Decided by James 2026-10-27. Two steps: S1 (convert the data, small), then S2
(remove the types from the code, one branch). Read with `CLAUDE.md` → Trips → "+ Add and five kinds" and
"'Choose one' groups and votes", and `docs/plans/day-first-planning.md` (P3, P4).

## Why

Day-first P3 replaced phases, callouts and free text with **notes**, and P4 replaced choose-your-adventure sections
with **"choose one" groups**. The old types are no longer offered by + Add, but they still exist: in trips that
haven't been converted, in the importers, in the section page's create URL (an editor could type
`…/sections/new/phase/`), in Tidy, in history restore and in about 30 test files. One way to write each thing.

## Decisions (James, 2026-10-27)

1. Retire **phase, callout and free text** together (`Section.OLD_NOTE_TYPES`).
2. Retire **choose your adventure** too: it leaves Add to this day, and leftovers become option groups.
3. **Logistics tables stay** for now: only the importer makes them, and they already have their own conversions
   (Turn into legs, Make it travel notes).

## S1 — Convert every trip (no model change)

- `manage.py convert_day_first`: add `--all` (every live trip; mutually exclusive with `--trip`; dry run unless
  `--apply`; prints per trip, then totals). One transaction and one history line per trip, as today.
- `day_first.plan` / `apply`: a choose-your-adventure section that can't become a group (today: one with a
  confirmation, left alone) becomes a **note** instead — the prompt as the heading, each option as a "• title —
  description (duration · cost)" paragraph — so its confirmation, comments and contacts stay on the same row and
  nothing is left over.
- Tests: `--all` dry run vs apply over two trips; the confirmation case now converts to a note with its links intact;
  `pending_count` is 0 afterwards.
- James runs it: dry run on dev (last night's copy of production), check a booklet or two, then on production
  `pg_dump` first and `convert_day_first --all --apply`.

## S2 — Remove the types (branch `retire-section-types`)

Do not merge S2 until S1 has run on production (see the migration below).

- **Create URL:** `section_create` accepts only `_add_section_types()` (404 otherwise). Add to this day loses
  **Choose your adventure** (it offers Note and Travel notes; choices come from + Add's Options / + Choose one).
- **Model:** remove `PHASE`, `CALLOUT`, `FREE_TEXT`, `CHOOSE_YOUR_ADVENTURE` from `Section.Type` and drop
  `OLD_NOTE_TYPES`; update the module docstring's payload list. The migration:
  1. converts any remaining phase / callout / free text in place to `note` with a **frozen copy** of the mapping in
     the migration file (never import `day_first`): phase heading → title, summary and highlights ("• ") →
     paragraphs; callout tone kept (info → tip), text → paragraphs; free text paragraphs kept; other payload keys
     kept;
  2. **stops with a clear error** if any choose-your-adventure section is left ("run `convert_day_first --all
     --apply` first: trips …"), because making option groups needs the real conversion;
  3. alters the field's choices (no table change; check with `sqlmigrate`).
- **Importers:** `docx_import` / `docx_europe` may keep their internal dict types while parsing, but
  `import_itinerary` must never save a section of a retired type: build notes and option groups straight from the
  parsed dicts. Refactor `day_first._as_note` / `_from_adventure` to work on plain dicts so the importer and S1 share
  one mapping; drop the post-import conversion step. Parser tests and the dry-run output change accordingly.
- **Forms and templates:** delete `PhasePayloadForm`, `CalloutPayloadForm`, `FreeTextPayloadForm`,
  `ChooseYourAdventurePayloadForm` and their entries in the payload-form map; remove the old-type branches from
  `partials/_section.html` and `pdf/booklet.html` (keep the `callout` CSS classes — notes with a tone use them).
- **Tidy:** `tidying._tidy_type` goes; rewrite the rules to read notes directly (a toned note where they read a
  callout, a heading-only note where they read a phase, paragraphs where they read free text). Keep the suggestion
  kind names and keys (`meal_phase`, `callout_task`, …) so existing `TidyDismissal`s still match.
- **History:** `changes.restore` of a removed section whose snapshot has a retired type restores it as a note
  (same frozen mapping); a choose-your-adventure snapshot restores as the note fallback from S1.
- **Conversion page and banner:** `trip_convert`, `convert_day_first` and Needs attention's "N sections to turn into
  notes" go once nothing can produce old types — keep only what still converts decision to-dos into groups (or
  remove that too if none are left on production; say which in the PR).
- **Elsewhere:** `unescape_html`, `public.py` / `audit_public_leak`, the admin, `tidy.py`'s docstring.
- **Tests:** switch fixtures that create the old types to notes / groups (about 30 files); add tests that the create
  URL 404s for each retired type, that the migration converts each old note type and refuses a leftover choose-your-
  adventure, and that restoring an old snapshot gives a note. The **booklet snapshot must not change** (its fixture
  already converts); if it does, find out why before updating it.
- **Docs:** CLAUDE.md (the "+ Add and five kinds", "'Choose one' groups", Tidy and importer bullets; add this plan's
  status), help guides that name phases, callouts or choose your adventure; bump their `updated`.
- Full suite in parallel; `makemigrations --check`; `check_layers.py`; `audit_public_leak` exits 0.
