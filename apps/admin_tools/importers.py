# admin_tools/importers.py
"""CSV import of activities and events for staff.

Each row is turned into the data the normal add/edit form expects (names are
looked up: category, country, region, city, activity) and validated by that
form (ActivityEditForm / EventForm), so an imported row obeys the same rules as
one typed in by hand. A row that matches an existing item (activity: same name;
event: same name and start date) updates it; blank cells keep the existing
value. ``preview()`` validates without saving; ``apply()`` saves the valid rows.
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.utils import timezone

from apps.activities.forms import ActivityEditForm
from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.forms import EventForm
from apps.events.models import Event
from apps.locations.models import City, Country, Region

MAX_ROWS = 1000
MONTHS = {m.lower(): i for i, m in Activity.MONTHS} | {m.lower()[:3]: i for i, m in Activity.MONTHS}
TRUE = {"yes", "y", "true", "t", "1", "x"}
FALSE = {"no", "n", "false", "f", "0"}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%b %d %Y", "%B %d %Y", "%d %B %Y")
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p")


# column -> (form field, kind). kind: text, choice, bool, date, time, months, number, or a lookup
ACTIVITY_COLUMNS = {
    "name": ("name", "text"), "category": ("category", "category"), "description": ("description", "text"),
    "short_description": ("short_description", "text"), "country": ("country", "country"),
    "region": ("region", "region"), "city": ("city", "city"), "place": ("suggested_location", "text"),
    "recurrence": ("recurrence", "choice"), "usual_months": ("usual_months", "months"),
    "timing_notes": ("suggested_timeframe", "text"), "skill_level": ("skill_level", "choice"),
    "fitness": ("fitness_required", "number"), "duration": ("duration_category", "choice"),
    "cost_level": ("cost_level", "choice"), "best_for": ("best_for", "choice"),
    "indoor_outdoor": ("indoor_outdoor", "choice"), "booking_required": ("booking_required", "bool"),
    "suitable_for_children": ("suitable_for_children", "bool"),
    "wheelchair_accessible": ("wheelchair_accessible", "bool"), "equipment_needed": ("equipment_needed", "text"),
    "safety_notes": ("safety_notes", "text"),
}
EVENT_COLUMNS = {
    "name": ("name", "text"), "start_date": ("start_date", "date"), "end_date": ("end_date", "date"),
    "start_time": ("start_time", "time"), "end_time": ("end_time", "time"), "all_day": ("is_all_day", "bool"),
    "activity": ("related_activity", "activity"), "category": ("category", "category"),
    "description": ("description", "text"), "short_description": ("short_description", "text"),
    "country": ("country", "country"), "city": ("city", "city"), "town": ("location_text", "text"),
    "venue": ("venue_name", "text"), "venue_address": ("venue_address", "text"), "organizer": ("organizer", "text"),
    "event_type": ("event_type", "choice"), "free": ("is_free", "bool"),
    "ticket_price_min": ("ticket_price_min", "number"), "ticket_price_max": ("ticket_price_max", "number"),
    "currency": ("currency", "text"), "ticket_url": ("ticket_url", "text"), "website": ("website", "text"),
    "what_to_bring": ("what_to_bring", "text"),
}
REQUIRED = {"activity": ("name", "category", "description"), "event": ("name", "start_date", "description")}
EXAMPLES = {
    "activity": {"name": "Oktoberfest", "category": "Festival", "description": "The world's largest beer festival.",
                 "country": "Germany", "city": "Munich", "recurrence": "yearly", "usual_months": "Sep, Oct",
                 "timing_notes": "Mid September to the first Sunday in October", "cost_level": "moderate",
                 "booking_required": "no"},
    "event": {"name": "Oktoberfest 2027", "start_date": "2027-09-18", "end_date": "2027-10-03",
              "activity": "Oktoberfest", "description": "Oktoberfest 2027 on the Theresienwiese.",
              "country": "Germany", "city": "Munich", "venue": "Theresienwiese", "free": "yes"},
}


def columns(kind):
    return ACTIVITY_COLUMNS if kind == "activity" else EVENT_COLUMNS


def template_csv(kind):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(columns(kind)))
    writer.writeheader()
    writer.writerow(EXAMPLES[kind])
    return out.getvalue()


@dataclass
class Row:
    number: int  # line number in the file (header is 1)
    title: str
    action: str = "create"  # create / update / error
    errors: list = field(default_factory=list)
    changes: list = field(default_factory=list)  # field labels an update changes
    form: object = None
    instance: object = None


def _norm(header):
    return (header or "").strip().lower().replace(" ", "_").replace("-", "_")


class Importer:
    def __init__(self, kind, text):
        self.kind = kind
        self.text = text
        self.rows = []
        self.file_errors = []

    # ---- lookups -------------------------------------------------------
    def _choice(self, form_field, value):
        for key, label in form_field.choices:
            if str(key).lower() == value.lower() or str(label).lower() == value.lower():
                return key
        raise ValueError(f"isn't one of: {', '.join(str(k) for k, _ in form_field.choices if k != '')}")

    def _country(self, value):
        country = Country.objects.filter(Q(name__iexact=value) | Q(iso_code__iexact=value) | Q(iso3_code__iexact=value)).first()
        if country is None:
            raise ValueError("isn't a country in the catalogue")
        return country

    def _convert(self, kind, form_field, value, cells):
        if kind == "text":
            return value
        if kind == "number":
            return value.replace(",", "")
        if kind == "bool":
            if value.lower() in TRUE:
                return True
            if value.lower() in FALSE:
                return False
            raise ValueError("should be yes or no")
        if kind == "choice":
            return self._choice(form_field, value)
        if kind == "date":
            for fmt in DATE_FORMATS:
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    pass
            raise ValueError("isn't a date (use YYYY-MM-DD)")
        if kind == "time":
            for fmt in TIME_FORMATS:
                try:
                    return datetime.strptime(value.upper(), fmt).time()
                except ValueError:
                    pass
            raise ValueError("isn't a time (use 20:00 or 8:00 PM)")
        if kind == "months":
            months = []
            for part in value.replace(";", ",").split(","):
                part = part.strip().lower()
                if not part:
                    continue
                month = int(part) if part.isdigit() else MONTHS.get(part)
                if month not in range(1, 13):
                    raise ValueError(f"has an unknown month “{part}”")
                months.append(month)
            return months
        if kind == "category":
            category = ActivityCategory.objects.filter(Q(name__iexact=value) | Q(slug__iexact=value)).first()
            if category is None:
                raise ValueError(f"isn't a category (use one of: {', '.join(ActivityCategory.objects.filter(is_active=True).values_list('name', flat=True))})")
            return category.pk
        if kind == "country":
            return self._country(value).pk
        if kind == "region":
            regions = Region.objects.filter(name__iexact=value)
            if cells.get("country"):
                regions = regions.filter(country=self._country(cells["country"]))
            if regions.count() != 1:
                raise ValueError("isn't a region in the catalogue" if not regions else "matches several regions; add the country")
            return regions.get().pk
        if kind == "city":
            cities = City.objects.filter(name__iexact=value, approval_status=ApprovalStatus.APPROVED)
            if cells.get("country"):
                cities = cities.filter(country=self._country(cells["country"]))
            if cells.get("region"):
                cities = cities.filter(region__name__iexact=cells["region"])
            if cities.count() > 1:
                raise ValueError("matches several cities; add the country or region")
            if not cities:
                return None  # handled by the caller: an unlisted town
            return cities.get().pk
        if kind == "activity":
            matches = Activity.get_public_activities().filter(name__iexact=value)
            if matches.count() != 1:
                raise ValueError("isn't a published activity" if not matches else "matches several activities")
            return matches.get().pk
        raise ValueError("unknown column type")

    # ---- matching ------------------------------------------------------
    def _existing(self, cells, data):
        if self.kind == "activity":
            matches = Activity.objects.filter(name__iexact=cells["name"])
        else:
            if not data.get("start_date"):
                return None
            matches = Event.objects.filter(name__iexact=cells["name"], start_date=data["start_date"])
        if matches.count() > 1:
            raise ValueError("matches several existing items with that name; fix them in the admin first")
        return matches.first()

    def _base_data(self, form_class, instance):
        """What the form starts from: the existing item's values, or the model defaults."""
        form = form_class(instance=instance) if instance else form_class()
        if instance is not None:
            data = model_to_dict(instance, fields=[f for f in form.fields if f not in ("picture", "remove_picture", "tags")])
            if "tags" in form.fields:
                data["tags"] = [t.pk for t in instance.tags.all()]
        else:
            data = {}
            model = form._meta.model
            for name in form.fields:
                try:
                    model_field = model._meta.get_field(name)
                except Exception:
                    continue
                if getattr(model_field, "has_default", None) and model_field.has_default():
                    data[name] = model_field.get_default()
        # Leave out empty values: a form treats [] as "no value" and would save NULL into
        # list (JSON) columns, whereas an omitted field keeps the model default / current value.
        return {k: v for k, v in data.items() if v is not None and v != []}

    # ---- main ----------------------------------------------------------
    def parse(self):
        reader = csv.DictReader(io.StringIO(self.text.lstrip("﻿")))
        if not reader.fieldnames:
            self.file_errors.append("The file is empty.")
            return self
        headers = {_norm(h): h for h in reader.fieldnames}
        known = columns(self.kind)
        unknown = [h for n, h in headers.items() if n not in known]
        if unknown:
            self.file_errors.append(f"Unknown column(s), ignored: {', '.join(unknown)}.")
        missing = [c for c in REQUIRED[self.kind] if c not in headers]
        if missing:
            self.file_errors.insert(0, f"Missing required column(s): {', '.join(missing)}.")
            return self

        form_class = ActivityEditForm if self.kind == "activity" else EventForm
        seen = {}
        for number, raw in enumerate(reader, start=2):
            if number - 1 > MAX_ROWS:
                self.file_errors.append(f"Only the first {MAX_ROWS} rows were read.")
                break
            cells = {_norm(k): (v or "").strip() for k, v in raw.items() if k and _norm(k) in known}
            if not any(cells.values()):
                continue
            row = Row(number=number, title=cells.get("name") or "(no name)")
            self.rows.append(row)
            probe = form_class()
            converted = {}
            for column, value in cells.items():
                if not value:
                    continue
                form_name, kind = known[column]
                try:
                    converted[form_name] = self._convert(kind, probe.fields.get(form_name), value, cells)
                except ValueError as exc:
                    row.errors.append(f"{column} “{value}” {exc}")
            if self.kind == "event" and cells.get("city") and converted.get("city") is None and "city" in converted:
                # Not in the catalogue: keep it as a typed town (staff can link it later).
                converted.pop("city")
                converted.setdefault("location_text", cells["city"])
            if self.kind == "activity" and cells.get("city") and converted.get("city") is None and "city" in converted:
                converted.pop("city")
                converted.setdefault("suggested_location", cells["city"])
            if row.errors:
                row.action = "error"
                continue
            try:
                instance = self._existing(cells, converted)
            except ValueError as exc:
                row.action, row.errors = "error", [str(exc)]
                continue
            key = (cells["name"].lower(), converted.get("start_date"))
            if key in seen:
                row.action, row.errors = "error", [f"same item as row {seen[key]}"]
                continue
            seen[key] = number

            if instance is not None:
                converted["name"] = instance.name  # matched ignoring capitals; keep the existing spelling
            data = self._base_data(form_class, instance)
            data.update(converted)
            if self.kind == "event" and converted.get("city"):
                data.pop("location_text", None)  # a catalogue city replaces a typed town
                data.pop("country", None)
            form = form_class(data=data, instance=instance)
            if not form.is_valid():
                row.action = "error"
                for name, errors in form.errors.items():
                    label = "row" if name == "__all__" else name
                    row.errors.extend(f"{label}: {e}" for e in errors)
                continue
            row.form, row.instance = form, instance
            if instance is not None:
                row.action = "update"
                row.changes = [form.fields[n].label or n for n in form.changed_data if n not in ("picture", "remove_picture")]
        return self

    @property
    def counts(self):
        return {a: sum(r.action == a for r in self.rows) for a in ("create", "update", "error")}

    def apply(self, user):
        """Save every valid row; staff imports are published."""
        now = timezone.now()
        done = []
        with transaction.atomic():
            for row in self.rows:
                if row.action == "error":
                    continue
                obj = row.form.save(commit=False)
                if row.instance is None:
                    obj.created_by = user
                    obj.approval_status = ApprovalStatus.APPROVED
                    obj.submitted_by, obj.submitted_at = user, now
                    obj.reviewed_by, obj.reviewed_at = user, now
                    if self.kind == "activity":
                        obj.visibility, obj.source = "public", "import"
                obj.save()
                row.form.save_m2m()
                done.append((row, obj))
        return done
