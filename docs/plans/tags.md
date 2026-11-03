# Tags: one set, on activities, that you can filter by

Decided 2026-11-03 (James). One phase, **TG1**, on branch `tg1-tags`.

Status: TG1 done 2026-11-03.

## Why

There are two tag models. Both were meant for the same thing: descriptors that cut across categories ("family-friendly",
"outdoor", "free", "food", "music"), so that you can browse "free outdoor things" where one category can't express it.

- **`activities.ActivityTag`** is half built. The activity form lets you pick tags (`user_can_add` decides which members
  may use), the activity page shows them as badges, and the CSV import keeps an activity's tags. But **nothing filters by
  them**: the activity list, the event list and search ignore tags. `usage_count` is only refreshed when a tag is saved
  in the admin.
- **`events.EventTag`** was never connected. It has no form field, page, filter or import column, only an admin page.

An event is one dated occurrence of an activity (Oktoberfest 2027 of Oktoberfest). Its descriptors belong to the activity,
and an event already takes its category and picture from its activity. So events **take their activity's tags**, and
`EventTag` goes. One set of tags then answers "family-friendly things to do", dated events included.

## Step 0: check the data (no writes)

On dev (last night's copy of production), read-only in `manage.py shell`: count `EventTag` rows and their event links,
`ActivityTag` rows, and how many public activities have at least one tag. Put the counts in the PR. **If any event has a
tag, stop and ask James** (the answer may be to copy those tags onto the event's activity first). Expected: no event tags.

## Step 1: remove `EventTag`

Delete the model (`apps/events/models.py`), its admin and the import in `apps/events/admin.py`. Run `makemigrations events`
and read the proposal: only `DeleteModel("EventTag")` (and its M2M table). Check it with `sqlmigrate`. Fix any docstring
that mentions event tags.

## Step 2: activity tags you can filter by

- **Activity list** (`activities:activity_list`): a **Tag** select beside Category (`?tag=<slug>`, filtered with
  `tags__slug`, `.distinct()`). Its options are the tags used by at least one public activity, with a count
  ("Outdoor (12)"), as one annotated query. The tag badges on the activity page become links to
  `activity_list?tag=<slug>`.
- **Event list** (`events:event_list`): the same `?tag=` through `related_activity__tags__slug`, with `.distinct()`.
  Events with no activity never match a tag. The Tag select's options and counts here are tags used by an activity
  with a visible upcoming event.
- **Event page:** shows its activity's tags as the same badge links (to the event list's `?tag=`), under the "Part of"
  card. No event has its own tags.
- **Search** (`pages.search`): `Filters.tag` (a slug). Like month and category, it leaves only activities and events
  (add it to `Filters.kinds()`; activities by `tags__slug`, events by `related_activity__tags__slug`). The filter row
  gets a Tag select. `test_search`'s fixed query count may rise by one for the select's options; if it does, change the
  pin on purpose and say so in the PR. It must stay fixed per page.
- **`usage_count`:** drop the field (an `activities` migration, `RemoveField` only). The admin's tag list shows the
  same number as an annotation (`Count("activities")`, sortable), so it is always right. Remove the count update from
  `ActivityTagAdmin.save_model`.
- **CSV import / export** (`admin_tools/importers.py`, activities only): a `tags` column holding tag names separated by
  `; `. Export writes them in name order. On import, a blank cell keeps the activity's tags (like every other blank
  cell), and names match existing tags ignoring capitals. An unknown name is a row error ("Unknown tag: Outdoorsy; add it
  in the admin first"), so imports never create tags. Update the import template's example row.
- Tags stay staff-managed in the admin. Members pick from tags with `user_can_add`, as they do now.

## Step 3: tests

- `apps/events/tests/`, or the existing place for event tests: the event page shows the activity's tags; `?tag=` on the
  event list keeps events whose activity has the tag, skips others and events with no activity, and lists each once.
- Activities: `?tag=` filters, the select lists only used tags with their counts, and the badges link.
- `test_search`: the tag filter leaves only activities and events, and the query count is fixed.
- `test_import`: the tags column round-trips (export → import), a blank cell keeps tags, and an unknown name is refused.
- Run `makemigrations --check`, the layer check and the full parallel suite. After the migrations, drop the parallel
  test copies first.

## Step 4: docs

- Update `apps/pages/help/places-and-events.md`, the guide on browsing activities and events: filter by tag, and
  "events show their activity's tags". Bump its `updated` date. If the import guide (`running-the-site.md`) lists the
  activity columns, add `tags` there.
- CLAUDE.md, in the **Lifecycle** bullet: "Tags are on activities only (`ActivityTag`; `EventTag` removed in TG1): an
  event shows and filters by its activity's tags; `?tag=` on the activity list, the event list and search; CSV `tags`
  column (`; `-separated names, existing tags only)." Mark this plan done in its CLAUDE.md section.

## Not in this phase

Tags on the catalogue cards, tags on places, and members creating new tags.
