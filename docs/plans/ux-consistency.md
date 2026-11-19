# Plan: one look across the site — tokens, shared partials, trip tabs, place pages, navigation

Status: V1 done on branch `v1-tokens`, V2 on branch `v2-shared-partials`, V3 on branch `v3-trip-tabs` (2026-11-19); V4–V5 not started. Hand to Claude Code **one phase per branch/PR, in order** (V1 → V5; "V" because the trip-page UX plan already uses U1–U7).
Read with `CLAUDE.md`. Each phase lists its **Ask James** decisions; stop and ask before the phase that needs them.
Every phase that changes something a user sees updates its Help guide in the same PR (`apps/pages/help/`, bump
`updated`). Mockups (current vs proposed, numbered notes):
<https://claude.ai/artifact/BkuQgRH7d3Qcr1pAo5sQe7>.

## Why

A UX review (2026-11-19) found the site running two design systems side by side, and most of the visible
inconsistencies come from that:

- **Two palettes.** `.trips-ui` (59 templates) draws in Tailwind's zinc (cool grey); the site's own `.sbl-*`
  components (137 templates) draw in warm grey. A trip page shows a grey shift right beside the warm sidebar.
- **Two of everything else.** Buttons (`.btn`/`.btn-quiet` vs `.sbl-btn-*`), badges (11 px uppercase vs sentence
  case), breadcrumbs (`<nav class="crumbs">` with "/" in 35 trips templates vs `partials/_breadcrumbs.html` with
  chevrons in 43), page titles (`sbl-page-title` ×54, `page-title` ×53, hand-set `text-4xl font-bold` in 13
  locations templates, plus the dashboard's gradient banner), filter bars (three patterns: bucket list applies on
  change; activities has a Filter button in a card; locations lists use a 12-column grid with Title Case labels).
- **Contrast.** `warm-500` (#8B7D71; `text-warm-500` ×341) is 3.7:1 on the page background and 4.0:1 on white —
  under the 4.5:1 minimum for body text. Sidebar group labels (`warm-400`) are 2.1:1. White text on sage (2.7:1),
  ochre (3.0:1, `sbl-btn-accent`) and tan (3.3:1) buttons fails.
- **Navigation.** From `lg` up the header repeats the sidebar's Dashboard / Bucket List / Trips links. One page is
  "Home" in the sidebar and "Dashboard" in the header; the dashboard's card says "Locations" where the sidebar says
  "Places"; "Rewards" opens the Travel profile. Three of the sidebar's five fold-up groups hold one link each. The
  dashboard's Quick Access cards repeat the sidebar, each with its own button colour.
- **Trip page.** The only filled button is Settings, so it reads as the main action. The Bookings / To do / Map …
  links have no current-page state and only show on the overview. The PDF menu and the more-actions menu are the
  text characters "▾" and "⋯".
- **Place pages.** Country, region, city and POI detail pages hand-build their header (sky-blue `#0ea5e9` fallback,
  7–10 inline `style=` each, "Approved" badge always shown, `font-semibold font-bold` headings) while activities and
  events share `partials/_detail_header.html`.
- **Leftovers.** `apps/core/static/core/css/design-system.css`, `design-system chat.css`, `design-system claude.css`
  and `site.css` aren't linked from any template; `theme/static_src/tailwind.config.js` isn't read by Tailwind 4
  (`styles.css` says so); `templates/components/home_example.html` is unused.

## Order and why

| Phase | What | Why here |
|---|---|---|
| V1 | Tokens: one warm palette, contrast fixes, dead files out | CSS only; fixes most of what you see with no template changes |
| V2 | Shared partials: page header, breadcrumbs, filter bar, badges, wording | Gives V3–V5 the pieces they build with |
| V3 | Trip tab bar and trip header actions | The most-used pages; needs V2's header and breadcrumbs |
| V4 | Place pages onto `_detail_header` | Same banner as activities and events |
| V5 | Navigation and dashboard | Biggest visible change and has the most to decide; goes last |

## Decisions (from the review)

1. **Warm everywhere.** Trips keep their class names (`card`, `chip`, `badge-*`, `callout-*`, `text-zinc-500` — the
   tests assert them) but they draw from the warm palette.
2. **One filled button per page**, for the page's main action (`sbl-btn-primary` / `.btn`). Everything else is
   outline, link or danger. Olive, ochre and sage stay as accents (progress bars, badges, pictures), never as
   white-text buttons.
3. **Sentence case** for every label, button, heading and page title: "Log in", "Log out", "Sign up", "Save changes",
   "Add a country".
4. **Badges are sentence case.** Status badges (Draft, Ready, Pending review, Done) carry a dot; label badges
   (a category, "Free") don't.
5. **Approved is the normal state**, so it gets no badge anywhere; only pending, rejected, changes requested and draft
   are shown (as `_detail_header` already does).

---

## V1 — Tokens: one warm palette, contrast fixes, dead files out (branch `v1-tokens`)

All in `theme/static_src/src/styles.css` plus a rebuilt `theme/static/css/dist/styles.css` (CI checks the committed
build matches).

- **Remap zinc to warm inside trips.** Tailwind 4 utilities read `var(--color-zinc-*)`, so one rule re-points every
  zinc utility and every `@apply`'d trips component without touching a template or a test:

  ```css
  .trips-ui {
    --color-zinc-50: var(--color-warm-50);   --color-zinc-100: var(--color-warm-100);
    --color-zinc-200: var(--color-warm-200); --color-zinc-300: var(--color-warm-300);
    --color-zinc-400: var(--color-warm-400); --color-zinc-500: var(--color-warm-500);
    --color-zinc-600: var(--color-warm-600); --color-zinc-700: var(--color-warm-700);
    --color-zinc-800: var(--color-warm-800); --color-zinc-900: var(--color-warm-900);
    --color-zinc-950: var(--color-warm-900);
  }
  ```

  Checked 2026-11-19: the committed build emits `.text-zinc-500{color:var(--color-zinc-500)}`, so this works. (If a
  later build ever inlines the values, fall back to replacing `zinc` with `warm` in the trips `@layer components`
  block and the trips templates, and update the four tests that assert `text-zinc-500`.) Also do the same remap for the two non-trips
  templates that use zinc (`locations/widgets/city_search.html`, `reviews/trip_rate.html`) and `.help-link-icon`, or
  switch those to warm classes directly. Check the booklet (`trips/pdf/`) and the email templates don't change.
- **Darken `warm-500`** to `#786A5F` (4.9:1 on `warm-50`, 5.2:1 on white). This must land in the same PR as the
  remap: zinc-500 passes today (4.8:1) and the old warm-500 doesn't, so the remap alone would make trips worse.
- **Sidebar group labels** `text-warm-400` → `text-warm-600` (in `partials/_sidebar.html`, the `step` class string).
  Look for other `text-warm-400` used on text people need to read (32 uses) and move those to `warm-600`; leave
  decorative ones (chevrons, separators).
- **Buttons that fail contrast.** `.sbl-btn-accent` → `bg-earth-ochre-dark hover:bg-earth-clay-dark`. The dashboard
  cards' sage and tan buttons go away in V5; until then point them at `earth-olive` / `earth-clay`.
- **Delete** the three `design-system*.css` files, `site.css`, `theme/static_src/tailwind.config.js` and
  `templates/components/home_example.html`, after grepping for any reference (templates, Python, `collectstatic`
  config). If `tailwind.config.js` turns out to be needed by `django-tailwind`'s tooling, keep it but replace the
  palette with a comment pointing at `styles.css`.
- **Tests:** a test that the built CSS contains the `.trips-ui` zinc remap and the new `warm-500` value; run the
  full suite (no template assertions should change).

**Ask James:** look at a trip page and the dashboard on dev with the new `warm-500` before merging — it's a
site-wide change to secondary text.

## V2 — Shared partials: page header, breadcrumbs, filter bar, badges, wording (branch `v2-shared-partials`)

- **`partials/_page_header.html`**: `title`, `subtitle`, optional `badge` (a status badge include), and an actions
  slot. Includes can't take blocks, so actions come as `actions_template="app/partials/_x_actions.html"` (or the page
  keeps its own actions `<div>` right after the include — pick whichever is smaller). Styles: `sbl-page-title`,
  `sbl-page-subtitle`. Convert every page with a hand-set `<h1>` (the 13 locations templates, `reviews/review_form`,
  the confirm-delete and form pages listed by `grep -lE '<h1 class="(text-4xl|text-2xl|mb-2 text-2xl|mb-4 text-2xl)'`).
  The trips `.page-title` / `.hero-title` stay as classes but match `sbl-page-title` (bold, warm-900, 3xl/4xl).
- **One breadcrumb.** Trips pages switch from hand-written `<nav class="crumbs">` to
  `partials/_breadcrumbs.html` (chevrons). The list can be built in the template with a small `{% breadcrumbs %}`
  tag or passed from views as `breadcrumb_list` like the rest of the site — whichever touches fewer files. Update the
  locator in `trips/tests/test_settings_and_views.py` (it searches for `<nav class="crumbs">`). Delete `.crumbs` from
  `styles.css` when nothing uses it.
- **`partials/_filter_bar.html`** for list pages: in an `sbl-card`, search + selects + sort, applies on change
  (`onchange="this.form.submit()"`) with a visible Go button for no-JS, a "Clear" link when anything is set, and the
  result count. Use it on activities, events, bucket list and the four locations lists.
- **Badges.** `.trips-ui .badge` drops `uppercase tracking-wider text-[11px]` for `text-xs` sentence case; the status
  variants keep their dots. Class names unchanged.
- **Empty states.** One partial (`components/feedback/empty_state.html` exists, used once): icon, title, text,
  optional primary and secondary action. Use it for the `sbl-card p-10 text-center` blocks and `.trips-ui
  .empty-state`, keeping the `empty-state` class on the trips wrapper if tests look for it.
- **Wording sweep** to sentence case: header (`Login` → `Log in`, `Logout` → `Log out`, `Sign Up` → `Sign up`, also
  `_header_simple.html`), accounts templates (`Log In`, `Save Changes`, `Save Preferences`, `Change Password`,
  `Reset Password`, `Send Reset`, `Resend Verification`), locations (`Add Country/Region/City` → "Add a country" …),
  and `<title>` blocks. Dashboard headings are handled in V5. Update tests that assert the old strings.
- **Tests:** a style test in the spirit of `pages/tests/test_catalogue_style.py`: every list page renders
  `_filter_bar` and every page's `<h1>` carries `sbl-page-title` or `page-title`/`hero-title` (walk the URL conf for
  a staff user and a normal user, skipping auth and admin).

## V3 — Trip tab bar and trip header actions (branch `v3-trip-tabs`)

- **`trips/partials/_trip_tabs.html`**: Overview · Bookings · To do · Map · Budget · Photos · People · History, a
  `<nav aria-label="Trip sections">` with `aria-current="page"` and a clay underline on the current one. Included on
  the trip page and every sub-page those links go to, under the page header. It replaces the row of `link-quiet`
  links on `trip_detail.html`. On a phone it scrolls sideways in its own box (`overflow-x-auto`, no wrapping).
- **Counts** (Bookings outstanding, To do open, People) only where the number is already in the view's context.
  **No new queries**: `trips/tests/test_detail.py` pins the trip page at 38 queries; run
  `manage.py perf_report --trip <pk>` before and after.
- **Breadcrumbs on sub-pages** become Trips › *trip name*; the tab shows which section you're in.
- **Header actions:** Settings becomes an outline button with a gear icon (not filled); Download PDF + its menu is
  one split outline button with a real chevron icon and `aria-label="More PDF choices"`; "⋯" becomes an icon button
  (Bootstrap Icons `bi-three-dots`, `aria-label="More actions"`). Keep every `data-*` hook the tests use
  (`data-settings-link`, `data-pdf-menu`, `data-pdf-plain`, `data-trip-menu`, …).
- **The outstanding-tasks note** on the trip page becomes an amber callout with a "Go to Bookings" link. (Done as
  "Go to To do": the note is Settings' Ready to go warning, and to-dos live on the To do page.)
- **Help:** `reading-your-trip.md` (the header and the new tabs).
- **Tests:** the tab bar renders on each sub-page with the right `aria-current`; the trip page's query count is
  unchanged.

## V4 — Place pages onto `_detail_header` (branch `v4-place-headers`)

- `country_detail`, `region_detail`, `city_detail`, `poi_detail` use `partials/_detail_header.html` like activities
  and events: `label` = "City · Capital" (kicker), `place` = region and country, `stars` when the place has reviews,
  `image` = its picture (flags already handled by `is_flag`), `status` / `status_label`. The fallback with no picture
  is the partial's clay, not sky blue.
- **Actions on the header**: "Add to bucket list" (`partials/_bucket_add_button.html`, primary) and "Plan a trip
  here" (`partials/_trip_add_button.html`, outline) in a strip under the banner, with a one-line summary
  ("12 activities · 4 events"), using counts the view already has. Add that strip to `_detail_header` as an optional
  `actions_template=` (activities and events can adopt it later) — or as a sibling partial; pick the smaller.
- No "Approved" badge (decision 5). Headings to `sbl-section-title`. Remove the inline `style=` (heights, object-fit,
  gradients) for Tailwind classes.
- **Help:** `places-and-events.md`.
- **Tests:** extend `pages/tests/test_catalogue_style.py` to the four place detail pages (banner header present, no
  "Approved" badge for an approved place, the bucket and trip buttons present).

## V5 — Navigation and dashboard (branch `v5-nav-dashboard`)

**Ask James before starting:** (1) "Home" or "Dashboard" for the signed-in start page — one name everywhere;
(2) what "Needs you" lists (suggested: outstanding booking tasks across upcoming trips, highest priority first;
trips waiting for a post-trip rating from R17; your submissions with changes requested); (3) whether Rewards keeps a
place in the sidebar or stays inside the Travel profile.

- **Header:** remove the Dashboard / Bucket List / Trips links (the sidebar shows them from `lg` up and the drawer
  below). Keep logo, search (wider), notifications, account menu, Admin for staff.
- **Sidebar** (`partials/_sidebar.html`, also the mobile drawer):
  - Home (or Dashboard), then **Discover**: Activities, Events, Places.
  - **Your journey**: Bucket list (Dream) · My dates (Pick a date) · Trips (Plan) · Adventures (Done) · Albums —
    a numbered rail with each step's lifecycle name as a small caption, no folding. Drops the `sbl-nav-*`
    localStorage keys and the Alpine fold code.
  - About & help at the bottom.
  - Rewrite `pages/tests/test_sidebar.py` for the new shape: order, captions, the current page highlighted.
- **Dashboard** (`pages/dashboard.html`):
  - Page header via `_page_header`: "Good morning / afternoon, *name*", the date; actions "Plan a trip" (outline),
    "Add a goal" (primary). Drops the gradient banner and the emoji.
  - Replace Quick Access (and `pages/partials/dashboard_card.html`) with three cards: **Next trip** (date tile, name,
    nights and cities, countdown, bookings done as a meter, Open trip), **Bucket list** (done of total, meter, three
    goals with their stage), **Needs you** (decision 2). Staff keep a small "Staff dashboard" / "Admin" link row.
  - "Recommended for you" keeps its cards; the reason pill uses `sbl-badge-primary` instead of
    emerald / fuchsia / sky / amber.
  - Recent Activity: keep or drop with James's answer to (2) — "Needs you" may make it redundant.
  - Sentence case headings. Watch the query count: reuse the annotations the bucket list dashboard already uses.
  - Update `pages/tests/test_staff_dashboard.py` (it finds "Quick Access" in the page).
- **Help:** `getting-started.md` (sidebar and dashboard), `bucket-list.md` if it mentions the sidebar groups.
- **Tests:** dashboard renders each card with and without data (no trips, no goals, nothing needing you); the header
  has no duplicate nav links; query count pinned.

## Not in this plan

- A dark theme, a new font, or a logo change.
- Turning the palette into a published design system; worth doing once V1–V2 settle the tokens and components.
- The trip page's day layout (see `trip-page-ux.md`, `day-first-planning.md`).
