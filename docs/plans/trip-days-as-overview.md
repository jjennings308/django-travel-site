# Plan: the folded days are the overview (drop the Overview table on the web)

Status: done (2026-10-23, branch `v1-days-as-overview`). The help-link "?" by Days points to the guide's new `#days-at-a-glance`; `#days` ("reading a day") stays in the guide. One branch, `v1-days-as-overview`. Read with `CLAUDE.md` →
"The web trip page is laid out for the web" and `docs/plans/trip-page-ux.md` (U2/U3).

## Why

The web trip page shows the same per-day facts twice: the **Overview** table (one row per day: where,
sleeping, travel, highlights, ⚠) and, right below it, the **folded days**, whose summary lines already
say the date and city. Now that the PDF booklet has its own layout (and its own "Days at a glance"
page, snapshot-guarded), the web page doesn't need the table: the list of folded days can *be* the
overview if each summary line carries what the table showed.

## What changes (web only — the booklet is untouched; its snapshot must not change)

1. **Remove the Overview table** (`table.trip-overview`) and the `#overview` section.
2. **Richer day summaries.** Each day's `<summary>` (`<details class="day-fold" id="day-N">`) shows:
   - line 1: **Day N · Mon Sep 20 · Augsburg** — the theme after it in muted text;
   - line 2 (muted, small): 🛏 the stay (`(check in)` / `(check out)`; "✈ overnight" when a leg that day
     arrives a day later), the travel icons + summary ("🚆 2 legs · ~3¼ h", or "A → B" for one leg), up to
     two highlights, and the amber **⚠N** when that day has not-booked items or open tasks.
   - Items with nothing to show are left out (no empty separators). On a phone line 2 wraps; highlights
     truncate first. The stay links (`#stay-N`) and ⚠ stay clickable without toggling the fold (stop
     the click from toggling, or put them outside the `<summary>`'s toggle area).
   - The data already exists: `itinerary.overview` sets `day.stay`, `day.overnight`, `day.travel_icons`,
     `day.travel_summary`, `day.highlights`, `day.attention` — reuse it, rename nothing the booklet uses.
3. **Needs attention becomes a banner** directly under the header (`#needs-attention`), shown only when
   there is something (not booked · to do · decisions · documents not ticked · not on any day · tables to
   convert), same links as today.
4. **About this trip** — a `<details id="about">` fold at the top of the Days section, **closed by
   default** (open when the trip has no days yet), holding what the Overview section held besides the
   table: travellers, cities, destination, the goals link, the bucket-list prompt, trip notes and the
   estimated trip cost (with its Budget link).
5. **Not on any day** — stray legs and stays outside the trip's days move to the top of the Days section
   (a short callout with their full cards, for everyone; the editors' "check its date" note stays).
6. **Tidy suggestions** link (editors) moves into the ⋯ menu.
7. **Jump bar:** Days · Reference. Old links to `#overview` (bookmarks, emails) land on `#days`: the
   page's existing hash script maps `overview` → `days` (and `about` opens the About fold).
8. **Help:** update `apps/pages/help/reading-your-trip.md` — the Overview section becomes "Days at a
   glance" (the summary lines and About this trip), bump `updated`; the trip page's "?" moves from
   Overview to Days; update `apps/pages/tests/test_help_links.py`'s expected anchors. Check every other
   guide and the FAQ for "Overview" and fix the wording.
9. **CLAUDE.md:** rewrite the "Overview (`#overview`)" bullet under "The web trip page is laid out for
   the web" to describe the summary lines, the banner and About this trip.

## Not changing

- The booklet (`trips/pdf/booklet.html`, its "Days at a glance" page) — the snapshot test must pass
  unchanged.
- Which day opens on arrival (`itinerary.open_day`), Expand all / Collapse all, Reference.
- Query count: the same data, so `QueryCountTests` stays where it is.

## Tests

- The trip page has no `trip-overview` table and no `#overview` section; the jump bar has Days and
  Reference.
- A day's summary shows its city, theme, stay (check-in/out wording), overnight flight, travel summary,
  highlights and ⚠ count — and leaves out what's empty.
- Needs attention banner: present with the right counts and links when something needs attention,
  absent otherwise.
- About this trip holds travellers, cities, goals link, notes and the cost estimate; closed by default,
  open when there are no days.
- Stray legs/stays still render (for a viewer too).
- The hash script maps `#overview` to `#days` (template contains the hook).
- Help link tests pass with the new anchors; booklet snapshot unchanged; query count unchanged.
- Phone (390 px): no sideways scroll; summary lines wrap; tap targets ≥ 44 px.

## Later, only if missed

If scanning sleeping/travel down the whole trip without opening anything turns out to be missed, a
"Compact view" toggle could show the summaries as a table again. Not part of this branch.
