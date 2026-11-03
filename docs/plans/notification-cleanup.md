# Notification clean-up

Decided 2026-11-03 (James). One phase, **NC1**, on branch `nc1-notification-cleanup`.

Status: NC1 done 2026-11-03 (notifications 0006).

## Why

The `notifications` app was scaffolded for push, SMS, quiet hours, digests and editable templates. None of
it was ever built. What the site really does is in-app notifications (the bell, `/notifications/`) plus
email through `services.notify()`, with a per-person, per-kind email switch
(`UserNotificationPreference.email_enabled`, the unsubscribe link). The trip change digest is already
batched by `trips` (`TripChange` + `send_trip_digests` → one `trip_changed` notification per trip), so
the generic digest model has no job.

Nothing outside `notifications/models.py` and `notifications/admin.py` reads or writes what is removed
below (checked 2026-11-03 with a grep over `apps/`, `templates/`, `scripts/`, migrations and tests aside).
If a "fewer emails" option is ever wanted, design it then: a `digest_sent_at` on `Notification` and a
per-kind Instant / Daily choice, not a separate digest table.

## Step 0: check the data first (no writes)

Dev's database is last night's copy of production, so count there, read-only (`manage.py shell`;
no `pg_dump` needed because nothing is written):

- rows in `NotificationDigest`, `NotificationTemplate`, `PushDevice`;
- `Notification` rows with `email_opened`, `push_sent` true or `scheduled_for` / `email_opened_at` /
  `push_sent_at` set;
- `UserNotificationPreference` rows where `push_enabled`, `in_app_enabled` or `sms_enabled` differ from
  their defaults, `frequency != "instant"` or `quiet_hours_enabled` is true;
- `NotificationType` rows where `title_template` / `message_template` are non-empty, `is_system` is true,
  or `default_push` / `default_in_app` differ from their defaults; `NotificationCategory` rows where
  `default_enabled` is false.

Write the counts in the PR description. **If any of the three tables has rows, or any field holds
something other than its default, stop and ask James** before removing that part. All zeros is the
expected answer.

## Step 1: models (`apps/notifications/models.py`)

Delete the models **`NotificationDigest`**, **`NotificationTemplate`** and **`PushDevice`**.

Delete these fields:

| Model | Fields |
|---|---|
| `Notification` | `email_opened`, `email_opened_at`, `push_sent`, `push_sent_at`, `scheduled_for`, plus the `Index(fields=['scheduled_for'])` |
| `UserNotificationPreference` | `push_enabled`, `in_app_enabled`, `sms_enabled`, `frequency` (and `FREQUENCY_CHOICES`), `quiet_hours_enabled`, `quiet_hours_start`, `quiet_hours_end` |
| `NotificationType` | `title_template`, `message_template`, `default_push`, `default_in_app`, `is_system` |
| `NotificationCategory` | `default_enabled` |

**Keep:** `Notification.channels` (`notify()` sets it, the admin shows it), `is_read` / `read_at`, the archive
fields and `archive()` (the admin's Archive action), `email_sent` / `email_sent_at`, `metadata`, `expires_at` /
`is_expired`, `NotificationType.default_email` (`notify()` sets it on a kind made on first use) and
`priority`, `UserNotificationPreference.email_enabled` and its `unique_together`. Fix any docstring or
help text that still mentions push, SMS, quiet hours or digests.

## Step 2: admin (`apps/notifications/admin.py`)

Remove the `NotificationDigest`, `NotificationTemplate` and `PushDevice` admins and their imports, and every
removed field from `list_display`, `list_filter` (`push_sent`), `fieldsets`, `readonly_fields` and
`search_fields` of the remaining admins. The Notification admin's "Delivery" fieldset keeps `channels` and
`expires_at`.

## Step 3: migration

`python manage.py makemigrations notifications` → `0006_…`. **Read the proposal**: it must hold only
`RemoveField`, `RemoveIndex` and `DeleteModel` operations for exactly the items above, and nothing for any
other app. Check `sqlmigrate notifications 0006` (drops only; no table renamed or rebuilt). The seed
migrations 0002–0005 set some of the removed fields; they run on their own historical state, so leave
them alone. No other app's migrations touch these models (checked).

Then drop the parallel test copies (`test_travel_site_1` … `_N`) or run once without `--keepdb`, as
CLAUDE.md says after any migration.

## Step 4: tests and checks

- `python manage.py test apps.notifications apps.pages --keepdb --noinput` while working (`pages` holds the
  cross-app notification flow tests and Your data, whose `notifications.json` is serialized from
  `Notification` and simply loses the removed keys; update a test only if it names a removed field).
- Add one test to `apps/notifications/tests/` (create the `tests/` package if it is still a stub): `notify()`
  still creates the notification, emails it, and honours `email_enabled = False` for that kind.
- `python scripts/check_layers.py`, `python manage.py makemigrations --check --dry-run` (no changes after
  0006), then the full suite: `.venv/bin/python manage.py test --keepdb --parallel --noinput`.
- Open `/admin/notifications/` in `runserver`: the four remaining admins load, list and open a row.

## Step 5: docs

In CLAUDE.md's **Notifications** bullet add one sentence: "The app does in-app and email only; push, SMS, quiet
hours, frequency, digests and editable templates were never built and were removed (notifications 0006,
NC1). If batching emails is ever wanted, add `digest_sent_at` to `Notification` rather than a digest table."
Mark this plan's status in its CLAUDE.md section.

## Deploying

Nothing user-facing changes. `deploy.sh` takes a `pg_dump` before running the pending migration, so the
dropped columns and tables are in that dump if anything is ever wanted back.

## Not in this phase

The other leftovers found on 2026-11-03 (unused `Event` fields and `EventTag` /
`EventSchedule`, `MediaCategory`, `core.SoftDeleteModel` / `PublishableModel`, leftover fields on `Review`,
`Media`, `BucketListItem`, the vendor and content-provider profiles, `ApprovalRule`'s auto fields,
`UserPreferences`, and finishing the locations `ReviewableMixin` → `Approvable` move) wait for James's
decision. The `vendors` app and `accounts.UserRole` stay on purpose.

**Correction (2026-11-03):** `EventPerformer` is in use and stays: the event admin's inline edits it and the event
page shows it as **Line-up** (`event.performers`). Only its `performer_type` field is unused.
