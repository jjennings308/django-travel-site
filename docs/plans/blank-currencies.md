# Plan: costs with no currency take the place's currency, not the reader's

Status: CU1 done on branch `cu1-blank-currencies` (2026-11-02). Run `manage.py fill_currencies --apply` on production
after the deploy. Found by James 2026-11-02 on Europe 2027. The Neuschwanstein and Hohenschwangau timed entries
show "≈ 52 pp" with no symbol, and the Budget page counts them as dollars. One phase, CU1. Read with `CLAUDE.md` →
Trips → "Currency choices", "Budget in one currency", "Budget estimates" (B1–B3).

## What's wrong

Items made before E4, or by paths that don't set a currency, have an amount but a **blank currency**. Those paths
include import, converted sections, ideas, and an option whose currency was blank before Pick copied it. A blank
currency then gets read three different ways:

- `costs.money(amount, "")` prints a bare number ("≈ 52 pp"), with no symbol or code.
- `budget_plan._Money.convert` treats blank as **the page's currency** (`currency or self.target`). The same €52
  therefore counts as $52 when you view the budget in USD, and as €52 when you view it in EUR.
- `currencies.setup` gives only **new** items the place's currency (`default_for`). Editing an existing item with a
  blank currency shows a blank or the first option, which is the home currency (USD). Saving then stores USD, which
  is wrong for Germany.

## Decision (2026-11-02)

**A cost always has a currency. When none was stored, it is the local currency of the item's place.** The place is
the activity's or meal's catalogue place, the stay's city, the leg's origin city, then the day's city. If none of
those gives a currency, it is the trip's home currency. This is `currencies.default_for` with the item's cities, the
same rule new items already follow. It never depends on who is reading.

## CU1 (branch `cu1-blank-currencies`)

- **One resolver.** `currencies.currency_of(item, trip, day=None)` returns the stored code, else `default_for(trip,
  <the item's city ids>)`. City ids come from `activity_city_ids` and the matching helpers for meal, stay, leg and
  option. It is pure over the trip's cached cities (`_currency_cache`), so it adds no queries. Use it in:
  - `costs.estimate` / `costs.note_for` / `costs.annotate` (the day's "≈ €52 pp");
  - `budget_plan` rows, so `_Money.convert` is never handed a blank currency. Keep the `or self.target` fallback
    only for expenses, which have a required currency;
  - `options._costs` / `_per_person`;
  - `budget_plan.to_pay` (the booklet's "To pay there");
  - `Option.kind_line` (the choice box).
  - Check the trip page and day fragment pins (38 / 36) and the budget page pin. They must not move.
- **Forms.** `currencies.setup` also starts an **existing** item whose stored currency is blank on `default_for`
  (not only new ones). Opening and saving it fixes it, and an Edit never quietly suggests USD for a German castle.
- **Fill the stored blanks once.** `manage.py fill_currencies [--trip <pk>] [--apply]` lists every leg, stay,
  activity, meal and option with an amount and a blank currency, and the code it would set ("Neuschwanstein Castle
  (Day 15): EUR, from Schwangau"). It is a dry run by default. `--apply` saves in one transaction under one history
  line per trip ("Filled in 6 missing currencies"). Items with no amount stay blank. Run it on production after the
  deploy; the PR says so.
- **A catalogue place's own price comes first.** When the activity's catalogue place has an entry fee with a
  currency (`POI.entry_fee` / `entry_fee_currency`, e.g. Hohenschwangau Castle EUR 21), `currency_of` for a trip
  activity with a blank currency uses that place's fee currency before the city's. Also, a trip activity linked to a
  place with an entry fee and **no estimate of its own** gets an offer on its page: "Use the castle's entry fee:
  €21 per person". It is never filled in silently.
- **Confirmations** with a `cost` and blank currency are handled the same way, from the places of the items they
  cover (`confirmation_city_ids`).
- **Tests:**
  - `currency_of` for each kind, falling back through place → city → day → home;
  - "≈ €52 pp" (not "≈ 52 pp") for a blank-currency activity at a German place;
  - the Budget page counts it as EUR converted to USD, not as USD;
  - the edit form starts a blank-currency item on EUR;
  - `fill_currencies` dry run lists, `--apply` saves with one history line, and skips items with no amount;
  - the pins hold; the booklet snapshot is unchanged (its fixture has currencies).
- **Help:** `budget`: "a cost is in the currency of the place unless you choose another". Bump `updated`.

## Not changing

- Expenses: their currency is already required.
- How a chosen currency is converted (ECB rates, Your own rates).
