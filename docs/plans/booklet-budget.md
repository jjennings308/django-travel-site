# Plan: an optional budget in the PDF booklet

Status: BB1 done (2026-10-31) on branch `bb1-booklet-budget`. Asked for by James 2026-10-31 ("the middle path").
Read with `CLAUDE.md` → Trips → "PDF booklet", "The booklet is snapshot-guarded", "Budget", "Budget in one
currency", and `docs/plans/budget-estimates.md` (B1–B3: `costs`, `budget_plan.plan`, an expense's **For**).

## Why

The booklet is what the group carries on the trip. A short money summary helps on the road ("what's paid, what's still
due, in what currency"), but a full budget would date quickly, clutter the booklet for people who don't want it, and
put who-paid-what in front of everyone who gets a copy. So: off by default, one page of totals, and a "to pay" line on
the items where money still changes hands.

## Decisions (James and Claude, 2026-10-31)

1. **Off by default.** The plain **Download PDF** is unchanged. A second choice, **PDF with budget**, adds it
   (`trips:trip_pdf?budget=1`). Anyone who can see the trip may use either (they can already see the Budget page);
   never public.
2. **One page, totals only**, at the end of the booklet after Reference: per category (Travel, Stays, Activities &
   tickets, Food, Other) and overall — planned, of which booked, paid, left to pay — in the **trip's home currency**,
   with "As of <date> · rates used: 1 EUR = 1.0842 USD (ECB, Oct 30)" and any amount left out for want of a rate
   listed ("Not converted: …"). Undecided choices as one line ("Undecided: 2 choices, €840–€1,240, not in the totals").
3. **No per-person table** in the booklet (who paid / owes what stays on the Budget page).
4. **"To pay" on items**, in the item's own currency (what you hand over there, never converted), only in the budget
   version:
   - a booked item whose booking cost is more than what's been recorded as paid for it (expenses whose **For** is the
     item or its confirmation): "To pay: €48 (booked €96, paid €48)";
   - an item marked **No booking needed** with an estimate, or an unbooked item with an estimate: "To pay there:
     ≈ €48";
   - fully paid: "Paid" (only when a payment is recorded for it; nothing is printed when the site doesn't know).
   A booking covering several items prints its line once, on its first item ("To pay: €120 for 4 journeys").
5. **The plain booklet doesn't change**, so its snapshot doesn't move.

## BB1 (branch `bb1-booklet-budget`)

- **Data** — reuse, don't re-derive: the summary comes from `budget_plan.plan` in the trip's `home_currency` with the
  trip's expenses. `trip_pdf` doesn't build `_trip_page_context`, so either call the same helper the Budget page uses
  or give `budget_plan` a small entry point that takes what `trip_pdf` already has (after `options.attach` and
  `_attach_confirmations`, so only what counts) plus one expenses query; say which in the PR. **Done the second way:**
  `budget_plan.booklet(trip, days, groups, expenses)` calls `plan` with a minimal context (trip, days, the option
  groups `trip_pdf` now loads once and hands to `options.attach`); the budget version costs one query more than the
  plain one. Nothing extra runs for the
  plain booklet (check with `assertNumQueries` on both).
- **"To pay"** — one pure function (in `budget_plan` or `costs`, next to `note_for`), `to_pay(item, payments)` →
  `None` / "Paid" / "To pay: …" / "To pay there: ≈ …", from the item's `confirmation_list`, its estimate and the
  payments by For key (`budget_plan`'s `keys`). The booklet sets `item.to_pay` only when `budget=1`.
- **Template** — `pdf/_budget.html` (the page: one table, the as-of / rates line, Not converted, Undecided) included
  at the end of `booklet.html` when `budget`; the item partials print `item.to_pay` under the item when it's set. The
  cover gets "Includes budget · as of <date>" in the budget version. File name: `<trip-slug>-booklet-budget.pdf`.
- **Trip page** — the header's **Download PDF** becomes a small menu (Alpine, like ⋯): **Download PDF** (unchanged
  URL) and **PDF with budget**; without JavaScript both show as links. The offline worker saves only the plain
  booklet (it never stores URLs with a query string) — say so in the help.
- **Tests** — the plain booklet's snapshot is unchanged; a second snapshot (`tests/snapshots/booklet_budget.html`,
  the same fixture plus a costed confirmation, a part payment, a no-booking-needed estimate, an undecided choice and a
  foreign amount with no rate) covers the budget version; `to_pay` cases (part paid, fully paid, nothing recorded,
  no booking needed, one booking over several items printed once, own currency kept); no per-person names on the
  page; query counts for both versions; the menu renders both links; `budget=1` refused for nobody who can't see the
  trip (404 as today).
- **Help** — `reading-your-trip` (the booklet section: the budget version, that it's a snapshot as of the date, the
  offline note) and `budget` (a pointer); bump `updated`.
- **Docs** — CLAUDE.md: the PDF booklet bullet gains the budget version and its snapshot; this plan's status.

## Not changing

- The Budget page, its per-person table and settle-up.
- The plain booklet and its snapshot.
- The public view (no budget, ever).
