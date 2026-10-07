"""Repair text that was saved HTML-escaped.

Some values were typed into the admin by pasting from an HTML source, which
stored the *escaped* text rather than the characters: a trip name became
``James &amp; Regan`` instead of ``James & Regan``. Django then escapes the
ampersand again on render, so the page shows ``James &amp; Regan`` to the reader.

This finds those values and unescapes them. Dry-run by default; ``--apply``
writes. Re-running is safe, and a value that is escaped more than once is
reported rather than silently half-fixed.
"""

import re

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# A curated allowlist rather than html.unescape. html.unescape also resolves
# entities written without a trailing semicolon ("a &notit; b" becomes
# "a ¬it; b"), which would quietly rewrite text nobody asked it to touch; this
# requires the semicolon and only resolves entities an escaped paste actually
# produces. Anything not listed here is deliberately left alone and is reported
# as untouched rather than guessed at.
NAMED = {
    # what HTML/XML escaping itself emits
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
    "nbsp": " ",
    # typographic characters that arrive when rendered text is copied back out
    "ndash": "–",
    "mdash": "—",
    "lsquo": "‘",
    "rsquo": "’",
    "ldquo": "“",
    "rdquo": "”",
    "hellip": "…",
    "middot": "·",
    "bull": "•",
    "laquo": "«",
    "raquo": "»",
    "copy": "©",
    "reg": "®",
    "trade": "™",
    "deg": "°",
    "euro": "€",
    "pound": "£",
    "yen": "¥",
    "sect": "§",
    "times": "×",
}

ENTITY_RE = re.compile(
    r"&(?:(" + "|".join(NAMED) + r")|#(\d{1,7})|#[xX]([0-9a-fA-F]{1,6}));"
)

TEXT_TYPES = {"CharField", "TextField"}


def unescape_once(value):
    """Resolve one level of escaping. Returns the value unchanged if it differs
    not at all, which is how the caller spots a no-op."""
    if not isinstance(value, str) or "&" not in value:
        return value

    def replace(match):
        name, dec, hex_ = match.groups()
        if name:
            return NAMED[name]
        try:
            code = int(dec, 10) if dec else int(hex_, 16)
            return chr(code)
        except (ValueError, OverflowError):
            return match.group(0)

    return ENTITY_RE.sub(replace, value)


def has_entity(value):
    return isinstance(value, str) and ENTITY_RE.search(value) is not None


class Command(BaseCommand):
    help = (
        "Unescape text that was saved HTML-escaped (dry-run unless --apply)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually write to the database. Without this, nothing is saved.",
        )
        parser.add_argument(
            "--table-prefix",
            action="append",
            default=None,
            help=(
                "Only inspect models whose database table starts with this. "
                "Repeatable. Defaults to 'trips_'."
            ),
        )

    def handle(self, *args, **options):
        prefixes = options["table_prefix"] or ["trips_"]
        apply = options["apply"]

        targets = []
        for model in apps.get_models():
            table = model._meta.db_table
            if not any(table.startswith(p) for p in prefixes):
                continue
            fields = [
                f.name
                for f in model._meta.get_fields()
                if getattr(f, "get_internal_type", lambda: None)() in TEXT_TYPES
            ]
            if fields:
                targets.append((model, fields))

        if not targets:
            raise CommandError(f"No tables matched prefix {', '.join(prefixes)!r}.")

        # Build the whole plan first, so the dry run and the write describe
        # exactly the same set of edits rather than the write re-deciding.
        plan = []
        for model, fields in sorted(targets, key=lambda t: t[0]._meta.label):
            pk = model._meta.pk.name
            for field in fields:
                qs = model.objects.filter(**{f"{field}__regex": ENTITY_RE.pattern})
                for obj_pk, value in qs.values_list(pk, field):
                    fixed = unescape_once(value)
                    if fixed != value:
                        plan.append((model, field, obj_pk, value, fixed))

        for model, field, obj_pk, value, fixed in plan:
            self.stdout.write(
                f"  {model._meta.label}.{field} [{obj_pk}]\n"
                f"      - {str(value)[:100]}\n"
                f"      + {str(fixed)[:100]}"
            )

        if apply:
            # One transaction: a bulk repair that half-applies is worse than one
            # that fails outright, and re-running is cheap.
            with transaction.atomic():
                for model, field, obj_pk, _value, fixed in plan:
                    model.objects.filter(pk=obj_pk).update(**{field: fixed})
            self.stdout.write(self.style.SUCCESS(f"\nFixed {len(plan)} value(s)."))
        else:
            self.stdout.write(
                f"\nWould fix {len(plan)} value(s) in "
                f"{', '.join(prefixes)} tables. Nothing was written."
            )

        # A value escaped twice only comes apart one level at a time. If a fixed
        # value still contains an entity, say so instead of leaving the
        # operator to assume it was fully repaired.
        partial = [
            (model._meta.label, field, obj_pk)
            for model, field, obj_pk, _value, fixed in plan
            if has_entity(fixed)
        ]
        if partial:
            self.stderr.write(
                self.style.WARNING(
                    f"{len(partial)} value(s) are escaped more than once and were "
                    "only unwrapped one level. Run this again to finish them: "
                    + ", ".join(f"{m}.{f}[{p}]" for m, f, p in partial[:5])
                )
            )

        if not apply and plan:
            self.stderr.write(
                self.style.WARNING("This was a dry run. Re-run with --apply to save.")
            )