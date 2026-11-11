# Short forms

## Context

James asked which input forms could have a short version with a way to expand to everything. The trip-item
pages are what + Add and the side panel open all the time. Today they show every field at once:
- journey: 22 fields
- activity: 17
- stay: 15
- meal: 14
- each choice option row: up to 18

He chose (2026-11-10):
- **Scope:** trip items only for this pass: journey, stay, activity, meal and the choice page's option rows. The
  event, catalogue activity, bucket-list goal and place forms may follow later.
- **Cost:** the amount and currency stay up front; **Cost is**, **People** and **Rooms** fold away. The preview line
  stays by the amount.
- **The fold:** stays closed and lists what's filled ("More details: operator, notes, 2 more"). It opens by itself
  only when a field inside has an error.

The goal is that each page shows what you need to plan or book the item, and everything else is one click away. No
field is removed, no data changes, no migration.

## Design

### One mechanism, declared per form
- **`MoreDetailsMixin`** (new, `apps/trips/forms.py`), next to `CostFieldsMixin`:
  - A form lists `MORE = (...)`, the field names that fold. Names the form lacks are skipped, so `InOptionMixin`
    dropping `option` is fine. A field added to a form later appears up front by default.
  - `more_fields`: the bound fields to fold.
  - `more_filled`: labels of folded fields holding a value. Ignore `None`, `""`, `[]`, `False`, `0` and `order`;
    count the cost basis only when not blank (blank = the kind's default).
  - `more_summary`: "operator, notes, 2 more" (first two, then a count).
  - `more_open`: any folded field has errors.
- **Field markers, never folded:** `travelers` (the panel's **people** tab, `data-panel-tab="people"`) and the
  cost amount (`cost_block_at`).
- **`apps/trips/templates/trips/_form_fields.html`:**
  1. The visible fields not in `more_fields`, as now. The `hide_fields` and cost-block rules are unchanged.
  2. Then, when there are folded fields:
     `<details class="mb-4" data-more-details data-panel-tab="details"{% if form.more_open %} open{% endif %}>`
     - The summary: "More details", plus ": {{ form.more_summary }}" when something is filled.
     - Inside, the same field markup.
  - Forms without the mixin render exactly as today (empty `more_fields`).
  - Every Django tag stays on one line (CLAUDE.md rule).
- **Without JavaScript:** a `<details>` still opens. Fields inside always submit, so saving never loses anything.

### Cost block split (`apps/trips/templates/trips/partials/_cost_fields.html`)
- **The partial gains `split` mode:**
  - Up front: amount, currency and the preview line.
  - New partial `partials/_cost_more.html`, rendered in the fold: **Cost is**, **People** (with its help text) and
    **Rooms** (still `x-show="rooms"`).
- **`CostFieldsMixin` gains `cost_split = False`:** the item forms set it to True. `cost_block_hidden` already
  keeps the general loop off these fields; the fold renders `_cost_more.html` where `cost_basis` would be.
- **Preview script:** `sblCostPreview(box)` reads its fields from the nearest `[data-cost-scope]`, else
  `box.closest("form")`. Today it reads them inside the box, but basis, people and rooms now sit in the fold.
  - The Alpine `x-data` / `@input` / `@change` move to that scope, so a change in the fold updates the preview and
    shows Rooms.
  - Item pages put `data-cost-scope` on the `<form>`.
  - The choice page puts it on each option's `<fieldset>`, because several options share one form.
- **The saved figure:** still computed only in `apps/trips/costs.py`.

### What folds, per form
| Form (page) | Up front | In **More details** |
|---|---|---|
| `LegEditForm` (`trips/leg_form.html`, grouped fieldsets) | Route: from / to (cities and names), mode. Schedule: date, departure, arrival. Details: operator, service number, cost + currency | zones (filled from the cities), ~duration, Cost is / People, notes, No booking needed, Placement (section, order, In option) |
| `LodgingForm` (`trips/stay_form.html`) | name, city, address, check in / out, nightly rate + currency | Cost is / People / Rooms, notes, No booking needed, In option, and **the pin** (latitude / longitude: the old "Adjust the pin" fold moves in, with its note) |
| `TripActivityForm` (`trips/activity_form.html`) | kind, title, start / end, catalogue place / event / typed place, travellers, estimate + currency | provider, Cost is / People, notes, No booking needed, order, In option |
| `MealPageForm` (`trips/meal_form.html`) | name, meal type, reservation time, catalogue place, estimate + currency | cuisine, price range, why recommended, reservation notes, Cost is / People, order, In option |
| `OptionForm` rows (`trips/group_form.html`) | title, the kind's place fields (catalogue place / activity / event / city / typed place, from / to), cost + currency | notes, link, nights override, mode override, Cost is / People / Rooms, order |

**The journey page.** It keeps its fieldsets (Route / Schedule / Details) for the up-front fields.
- One **More details** fold follows them, with small sub-headings for the folded groups: Schedule, Cost, Notes &
  booking, Placement.
- `LegEditForm.grouped()` skips folded names; a new `grouped_more()` gives the fold's groups.
- **Return trip** becomes its own closed fold, "Also add the return trip". It opens when `add_return` is ticked or
  one of its fields has an error.
- The zone-fill script is unchanged: it finds the zone inputs by name in the form, inside or outside the fold.

**Choice option rows.** Each option's fieldset gets its own small fold, "More about this option…", from the same
mixin. The `x-show` kind rules on the choice's own fields are unchanged.

**Left as they are:**
- The day page's Meals formset (`MealForm`, a table).
- Settings (`TripForm`), Day details, to-dos, confirmations, contacts, the admin's forms.
- The booklet, so the snapshot holds.

## Files
- `apps/trips/forms.py`:
  - `MoreDetailsMixin`.
  - `MORE` on `LegEditForm`, `LodgingForm`, `TripActivityForm`, `MealPageForm`, `OptionForm`.
  - `cost_split` on `CostFieldsMixin`.
  - `LegEditForm.grouped()` / `grouped_more()`.
- `apps/trips/templates/trips/_form_fields.html`: the fold.
- `apps/trips/templates/trips/partials/_cost_fields.html`, new `partials/_cost_more.html`: the split and the scoped
  preview.
- Templates:
  - `trips/leg_form.html`: the fold and the return-trip fold.
  - `trips/stay_form.html`: the pin moves into the fold (`hide_fields` no longer needed).
  - `trips/group_form.html`: a fold per option row.
  - `trips/activity_form.html`, `trips/meal_form.html`: `data-cost-scope` on the form.
- `apps/pages/help/adding-a-day.md`, `travel-legs.md`, `options-and-votes.md` (and `budget.md` where it says where
  **Cost is** is): say that the rest is under **More details**, and bump `updated`.
- `CLAUDE.md`: a short **Trip-item forms** paragraph (the mixin, `MORE`, the rules: people tab and cost amount never
  fold, opens on error, summary of what's filled).
- `tailwind build`, and commit `styles.css` if it changes.
- Branch `f1-short-item-forms`; plan file `docs/plans/short-forms.md` (this plan, with a "later" list: event,
  catalogue activity, goal, places).

## Tests (new `apps/trips/tests/test_short_forms.py`)
- **Each of the five pages** (journey, stay, activity, meal, choice):
  - The up-front fields come before `data-more-details`.
  - Each `MORE` field is inside it.
  - `travelers` and the cost amount are never inside it.
- **Summary:** lists filled fields ("operator, notes") and "N more", and stays closed. A folded field with an error
  renders `open`.
- **Saving:** posting the whole form, folded fields included, saves them all. Reuse the
  `ActivityPageTests`-style post-everything-from-the-context pattern from `test_blank_currencies.py`.
- **Cost:** with `cost_split`, `data-cost-scope` is on the form (or the option fieldset). `data-cost-preview` stays
  up front. **Cost is** / **People** / **Rooms** are in the fold.
- **Journey:** the return-trip fold is closed by default and open when `add_return` is posted with an error.
- **Stay:** latitude / longitude are inside More details, and the old `data-adjust-pin` fold is gone. Update
  `test_stays` (or wherever) if it asserts `data-adjust-pin`.
- **Existing suites:** existing tests should still pass, since every field is still rendered. The query pins
  (detail 38, day fragment 36, Settings 19) are untouched: no queries are added.

## Verification
1. `.venv/bin/python manage.py test apps.trips --keepdb --noinput`, then the full suite in parallel. Drop the
   `test_travel_site_N` copies first: 0063 is new.
2. `ruff check`, `ruff format --check --no-cache`, `scripts/check_layers.py`, `makemigrations --check` (expect no
   changes), `tailwind build`.
3. Dev browser check (back up dev first, accept legal on the admin, Playwright as before):
   - Open a journey, a stay, an activity and a meal from the trip page **in the side panel** and at **390 px**.
   - Check the short form, the fold summary, and that opening the fold shows Cost is / People with the preview
     updating, and Rooms on "per room per night".
   - Check the people tab still holds Travellers.
   - Save with something in the fold and see it kept.
   - On the choice page, check each option row's fold.
   - Restore dev.
4. Report, then ask to merge.

## Status

F1 (trip items) done on branch `f1-short-item-forms`. On the way: the choice page was a 500 for a stay choice on a
trip with no cities (`forms.share_choices` keyed selects by their SQL, which an empty list can't print); fixed.

## Later (not started)

The same mixin pattern for member-facing catalogue and goal forms, each its own phase when wanted:
- the event form (27 fields),
- the full catalogue activity form (35; its quick form stays),
- the bucket-list goal (16),
- the place / city / region edit pages.
