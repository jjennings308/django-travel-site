# admin_tools/importers.py
"""CSV import and export for staff: activities, events, countries, regions,
cities and places (POIs).

Each kind is described once in KINDS: its columns (CSV column -> form field and
how to read the cell), the required columns, the form that validates a row, how
a row finds the existing item it updates, and an example row. Activities and
events use the site's own add/edit forms (ActivityEditForm / EventForm);
locations, which have no such forms, use the small model forms below. Either
way an imported row obeys the model's rules.

Import: names are looked up (category, country, region, city, activity); a row
that matches an existing item updates it and blank cells keep the existing
value; ``parse()`` validates without saving and ``apply()`` saves the valid
rows (published). Export writes the published items in the same columns, so a
file can be exported, edited and imported again.
"""
import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

from django import forms
from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.utils import timezone

from apps.activities.forms import ActivityEditForm
from apps.activities.models import Activity, ActivityCategory
from apps.approval_system.models import ApprovalStatus
from apps.events.forms import EventForm
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region

MAX_ROWS = 5000
MONTHS = {m.lower(): i for i, m in Activity.MONTHS} | {m.lower()[:3]: i for i, m in Activity.MONTHS}
MONTH_ABBR = {i: m[:3] for i, m in Activity.MONTHS}
TRUE = {"yes", "y", "true", "t", "1", "x"}
FALSE = {"no", "n", "false", "f", "0"}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%b %d %Y", "%B %d %Y", "%d %B %Y")
TIME_FORMATS = ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p")
APPROVED = ApprovalStatus.APPROVED


# ---- forms for locations (they have no site forms) ----------------------------
class CountryImportForm(forms.ModelForm):
    class Meta:
        model = Country
        fields = ["name", "iso_code", "iso3_code", "continent", "latitude", "longitude", "currency_code",
                  "currency_name", "phone_code", "flag_emoji", "description", "travel_tips", "visa_required", "visa_info"]


class RegionImportForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ["country", "name", "code", "latitude", "longitude", "description"]


class CityImportForm(forms.ModelForm):
    class Meta:
        model = City
        fields = ["country", "region", "name", "latitude", "longitude", "timezone", "elevation_m", "population",
                  "capital_type", "best_time_to_visit", "average_daily_budget", "description"]

    def clean(self):
        cleaned = super().clean()
        country, region = cleaned.get("country"), cleaned.get("region")
        if country and region and region.country_id != country.pk:
            self.add_error("region", f"{region.name} is not in {country.name}.")
        return cleaned


class POIImportForm(forms.ModelForm):
    class Meta:
        model = POI
        fields = ["city", "name", "poi_type", "latitude", "longitude", "elevation_m", "address", "description",
                  "website", "phone", "entry_fee", "entry_fee_currency", "typical_duration",
                  "wheelchair_accessible", "parking_available"]


# ---- the kinds ------------------------------------------------------------
# column -> (form field or None for a lookup-only column, how to read it)
@dataclass
class Kind:
    label: str
    model: type
    form: type
    columns: dict
    required: tuple
    example: dict
    url_name: str
    order: tuple  # export order


KINDS = {
    "country": Kind(
        "Countries", Country, CountryImportForm,
        {"name": ("name", "text"), "iso_code": ("iso_code", "text"), "iso3_code": ("iso3_code", "text"),
         "continent": ("continent", "choice"), "latitude": ("latitude", "number"), "longitude": ("longitude", "number"),
         "currency_code": ("currency_code", "text"), "currency_name": ("currency_name", "text"),
         "phone_code": ("phone_code", "text"), "flag_emoji": ("flag_emoji", "text"),
         "description": ("description", "text"), "travel_tips": ("travel_tips", "text"),
         "visa_required": ("visa_required", "bool"), "visa_info": ("visa_info", "text")},
        ("name", "iso_code", "iso3_code", "continent"),
        {"name": "Iceland", "iso_code": "IS", "iso3_code": "ISL", "continent": "Europe", "latitude": "64.9631",
         "longitude": "-19.0208", "currency_code": "ISK", "currency_name": "Icelandic króna", "visa_required": "no"},
        "locations:country_detail", ("name",)),
    "region": Kind(
        "Regions", Region, RegionImportForm,
        {"name": ("name", "text"), "country": ("country", "country"), "code": ("code", "text"),
         "latitude": ("latitude", "number"), "longitude": ("longitude", "number"),
         "description": ("description", "text")},
        ("name", "country"),
        {"name": "Bavaria", "country": "Germany", "code": "BY", "latitude": "48.7904", "longitude": "11.4979"},
        "locations:region_detail", ("country__name", "name")),
    "city": Kind(
        "Cities", City, CityImportForm,
        {"name": ("name", "text"), "country": ("country", "country"), "region": ("region", "region"),
         "latitude": ("latitude", "number"), "longitude": ("longitude", "number"), "timezone": ("timezone", "text"),
         "elevation_m": ("elevation_m", "number"), "population": ("population", "number"),
         "capital": ("capital_type", "choice"), "best_time_to_visit": ("best_time_to_visit", "text"),
         "average_daily_budget": ("average_daily_budget", "number"), "description": ("description", "text")},
        ("name", "country", "latitude", "longitude"),
        {"name": "Munich", "country": "Germany", "region": "Bavaria", "latitude": "48.1351", "longitude": "11.5820",
         "timezone": "Europe/Berlin", "population": "1512491", "capital": "region"},
        "locations:city_detail", ("country__name", "name")),
    "poi": Kind(
        "Places (POIs)", POI, POIImportForm,
        {"name": ("name", "text"), "city": ("city", "city_required"), "region": (None, "context"),
         "country": (None, "context"), "type": ("poi_type", "choice"), "latitude": ("latitude", "number"),
         "longitude": ("longitude", "number"), "elevation_m": ("elevation_m", "number"),
         "address": ("address", "text"), "description": ("description", "text"), "website": ("website", "text"),
         "phone": ("phone", "text"), "entry_fee": ("entry_fee", "number"),
         "entry_fee_currency": ("entry_fee_currency", "text"), "typical_duration": ("typical_duration", "number"),
         "wheelchair_accessible": ("wheelchair_accessible", "bool"), "parking_available": ("parking_available", "bool")},
        ("name", "city", "latitude", "longitude"),
        {"name": "Theresienwiese", "city": "Munich", "region": "Bavaria", "country": "Germany", "type": "entertainment",
         "latitude": "48.1316", "longitude": "11.5498", "wheelchair_accessible": "yes"},
        "locations:poi_detail", ("city__country__name", "city__name", "name")),
    "activity": Kind(
        "Activities", Activity, ActivityEditForm,
        {"name": ("name", "text"), "category": ("category", "category"), "description": ("description", "text"),
         "short_description": ("short_description", "text"), "country": ("country", "country"),
         "region": ("region", "region"), "city": ("city", "city"), "place": ("suggested_location", "text"),
         "venue": ("venue", "poi"), "recurrence": ("recurrence", "choice"), "usual_months": ("usual_months", "months"),
         "timing_notes": ("suggested_timeframe", "text"), "skill_level": ("skill_level", "choice"),
         "fitness": ("fitness_required", "number"), "duration": ("duration_category", "choice"),
         "cost_level": ("cost_level", "choice"), "best_for": ("best_for", "choice"),
         "indoor_outdoor": ("indoor_outdoor", "choice"), "booking_required": ("booking_required", "bool"),
         "suitable_for_children": ("suitable_for_children", "bool"),
         "wheelchair_accessible": ("wheelchair_accessible", "bool"), "equipment_needed": ("equipment_needed", "text"),
         "safety_notes": ("safety_notes", "text")},
        ("name", "category", "description"),
        {"name": "Oktoberfest", "category": "Festival", "description": "The world's largest beer festival.",
         "country": "Germany", "city": "Munich", "recurrence": "yearly", "usual_months": "Sep;Oct",
         "timing_notes": "Mid September to the first Sunday in October", "cost_level": "moderate",
         "booking_required": "no"},
        "activities:activity_detail", ("name",)),
    "event": Kind(
        "Events", Event, EventForm,
        {"name": ("name", "text"), "start_date": ("start_date", "date"), "end_date": ("end_date", "date"),
         "start_time": ("start_time", "time"), "end_time": ("end_time", "time"), "all_day": ("is_all_day", "bool"),
         "activity": ("related_activity", "activity"), "category": ("category", "category"),
         "description": ("description", "text"), "short_description": ("short_description", "text"),
         "country": ("country", "country"), "city": ("city", "city"), "town": ("location_text", "text"),
         "place": ("poi", "poi"), "venue": ("venue_name", "text"), "venue_address": ("venue_address", "text"), "organizer": ("organizer", "text"),
         "event_type": ("event_type", "choice"), "free": ("is_free", "bool"),
         "ticket_price_min": ("ticket_price_min", "number"), "ticket_price_max": ("ticket_price_max", "number"),
         "currency": ("currency", "text"), "ticket_url": ("ticket_url", "text"), "website": ("website", "text"),
         "what_to_bring": ("what_to_bring", "text")},
        ("name", "start_date", "description"),
        {"name": "Oktoberfest 2027", "start_date": "2027-09-18", "end_date": "2027-10-03", "activity": "Oktoberfest",
         "description": "Oktoberfest 2027 on the Theresienwiese.", "country": "Germany", "city": "Munich",
         "venue": "Theresienwiese", "free": "yes"},
        "events:event_detail", ("start_date", "name")),
}
# The order to import a full set in (each kind looks up the ones before it).
IMPORT_ORDER = ("country", "region", "city", "poi", "activity", "event")


def template_csv(kind):
    spec = KINDS[kind]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(spec.columns))
    writer.writeheader()
    writer.writerow(spec.example)
    return out.getvalue()


# ---- export ---------------------------------------------------------------
def _cell(obj, kind, column, form_field, how):
    """One exported cell: the inverse of Importer._convert."""
    if how == "context":  # POI region / country, from its city
        city = obj.city
        place = city.region if column == "region" else city.country
        return place.name if place else ""
    if kind == "event" and column == "country":
        country = obj.place_country
        return country.name if country else ""
    value = getattr(obj, form_field, None)
    if value is None or value == "":
        return ""
    if how == "bool":
        return "yes" if value else "no"
    if how == "date":
        return value.isoformat()
    if how == "time":
        return value.strftime("%H:%M")
    if how == "months":
        return ";".join(MONTH_ABBR[m] for m in sorted(value) if m in MONTH_ABBR)
    if how in ("category", "country", "region", "city", "city_required", "activity", "poi"):
        return value.name
    return str(value)


def export_queryset(kind):
    spec = KINDS[kind]
    qs = spec.model.objects.filter(approval_status=APPROVED)
    if kind == "activity":
        qs = qs.filter(visibility="public").select_related("category", "country", "region", "city", "venue")
    elif kind == "event":
        qs = qs.select_related("category", "country", "city__country", "related_activity", "poi")
    elif kind == "region":
        qs = qs.select_related("country")
    elif kind == "city":
        qs = qs.select_related("country", "region")
    elif kind == "poi":
        qs = qs.select_related("city__country", "city__region")
    return qs.order_by(*spec.order)


def export_csv(kind, out):
    """Write the published items of ``kind`` to ``out`` in the import columns; returns the row count."""
    spec = KINDS[kind]
    writer = csv.writer(out)
    writer.writerow(list(spec.columns))
    n = 0
    for obj in export_queryset(kind):
        writer.writerow([_cell(obj, kind, col, ff, how) for col, (ff, how) in spec.columns.items()])
        n += 1
    return n


# ---- import ---------------------------------------------------------------
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
        self.spec = KINDS[kind]
        self.text = text
        self.rows = []
        self.file_errors = []

    # ---- reading cells ---------------------------------------------------
    def _choice(self, form_field, value):
        for key, label in form_field.choices:
            if key != "" and (str(key).lower() == value.lower() or str(label).lower() == value.lower()):
                return key
        raise ValueError(f"isn't one of: {', '.join(str(k) for k, _ in form_field.choices if k != '')}")

    def _country(self, value):
        country = Country.objects.filter(Q(name__iexact=value) | Q(iso_code__iexact=value) | Q(iso3_code__iexact=value)).first()
        if country is None:
            raise ValueError("isn't a country in the catalogue")
        return country

    def _city(self, value, cells):
        cities = City.objects.filter(name__iexact=value, approval_status=APPROVED)
        if cells.get("country"):
            cities = cities.filter(country=self._country(cells["country"]))
        if cells.get("region"):
            cities = cities.filter(region__name__iexact=cells["region"])
        if cities.count() > 1:
            raise ValueError("matches several cities; add the country or region")
        return cities.first()

    def _convert(self, how, form_field, value, cells):
        if how == "text":
            return value
        if how == "number":
            return value.replace(",", "")
        if how == "bool":
            if value.lower() in TRUE:
                return True
            if value.lower() in FALSE:
                return False
            raise ValueError("should be yes or no")
        if how == "choice":
            return self._choice(form_field, value)
        if how == "date":
            for fmt in DATE_FORMATS:
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    pass
            raise ValueError("isn't a date (use YYYY-MM-DD)")
        if how == "time":
            for fmt in TIME_FORMATS:
                try:
                    return datetime.strptime(value.upper(), fmt).time()
                except ValueError:
                    pass
            raise ValueError("isn't a time (use 20:00 or 8:00 PM)")
        if how == "months":
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
        if how == "category":
            category = ActivityCategory.objects.filter(Q(name__iexact=value) | Q(slug__iexact=value)).first()
            if category is None:
                names = ", ".join(ActivityCategory.objects.filter(is_active=True).values_list("name", flat=True))
                raise ValueError(f"isn't a category (use one of: {names})")
            return category.pk
        if how == "country":
            return self._country(value).pk
        if how == "region":
            regions = Region.objects.filter(name__iexact=value)
            if cells.get("country"):
                regions = regions.filter(country=self._country(cells["country"]))
            if regions.count() != 1:
                raise ValueError("isn't a region in the catalogue" if not regions else "matches several regions; add the country")
            return regions.get().pk
        if how == "city":
            city = self._city(value, cells)
            return city.pk if city else None  # None: an unlisted town, handled by the caller
        if how == "city_required":
            city = self._city(value, cells)
            if city is None:
                raise ValueError("isn't a city in the catalogue (import the cities first)")
            return city.pk
        if how == "poi":
            places = POI.objects.filter(name__iexact=value, approval_status=APPROVED)
            if cells.get("city"):
                places = places.filter(city__name__iexact=cells["city"])
            if cells.get("country"):
                places = places.filter(city__country=self._country(cells["country"]))
            if places.count() != 1:
                raise ValueError("isn't a place in the catalogue (import the places first)" if not places
                                 else "matches several places; add the city")
            return places.get().pk
        if how == "activity":
            matches = Activity.get_public_activities().filter(name__iexact=value)
            if matches.count() != 1:
                raise ValueError("isn't a published activity" if not matches else "matches several activities")
            return matches.get().pk
        raise ValueError("unknown column type")

    # ---- matching an existing item --------------------------------------
    def _existing(self, cells, data):
        model = self.spec.model
        if self.kind == "country":
            matches = model.objects.filter(iso_code__iexact=cells["iso_code"]) if cells.get("iso_code") \
                else model.objects.filter(name__iexact=cells["name"])
        elif self.kind in ("region", "city"):
            if not data.get("country"):
                return None
            matches = model.objects.filter(country_id=data["country"], name__iexact=cells["name"])
        elif self.kind == "poi":
            if not data.get("city"):
                return None
            matches = model.objects.filter(city_id=data["city"], name__iexact=cells["name"])
        elif self.kind == "event":
            if not data.get("start_date"):
                return None
            matches = model.objects.filter(name__iexact=cells["name"], start_date=data["start_date"])
        else:
            matches = model.objects.filter(name__iexact=cells["name"])
        if matches.count() > 1:
            raise ValueError("matches several existing items with that name; fix them in the admin first")
        return matches.first()

    def _match_key(self, cells, data):
        """What makes two rows in one file the same item."""
        if self.kind == "country":
            return (cells.get("iso_code") or cells["name"]).lower()
        if self.kind in ("region", "city"):
            return (data.get("country"), cells["name"].lower())
        if self.kind == "poi":
            return (data.get("city"), cells["name"].lower())
        if self.kind == "event":
            return (cells["name"].lower(), data.get("start_date"))
        return cells["name"].lower()

    def _base_data(self, instance):
        """What the form starts from: the existing item's values, or the model defaults."""
        form_class = self.spec.form
        form = form_class(instance=instance) if instance else form_class()
        if instance is not None:
            data = model_to_dict(instance, fields=[f for f in form.fields if f not in ("picture", "remove_picture", "tags")])
            if "tags" in form.fields:
                data["tags"] = [t.pk for t in instance.tags.all()]
        else:
            data = {}
            for name in form.fields:
                try:
                    model_field = self.spec.model._meta.get_field(name)
                except Exception:
                    continue
                if getattr(model_field, "has_default", None) and model_field.has_default():
                    data[name] = model_field.get_default()
        # Leave out empty values: a form treats [] as "no value" and would save NULL into
        # list (JSON) columns, whereas an omitted field keeps the model default / current value.
        return {k: v for k, v in data.items() if v is not None and v != []}

    # ---- main ------------------------------------------------------------
    def parse(self):
        reader = csv.DictReader(io.StringIO(self.text.lstrip("﻿")))
        if not reader.fieldnames:
            self.file_errors.append("The file is empty.")
            return self
        headers = {_norm(h): h for h in reader.fieldnames}
        known = self.spec.columns
        unknown = [h for n, h in headers.items() if n not in known]
        if unknown:
            self.file_errors.append(f"Unknown column(s), ignored: {', '.join(unknown)}.")
        missing = [c for c in self.spec.required if c not in headers]
        if missing:
            self.file_errors.insert(0, f"Missing required column(s): {', '.join(missing)}.")
            return self

        form_class = self.spec.form
        probe = form_class()
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
            missing_cells = [c for c in self.spec.required if not cells.get(c)]
            if missing_cells:
                row.action, row.errors = "error", [f"{c} is required" for c in missing_cells]
                continue
            converted = {}
            for column, value in cells.items():
                form_name, how = known[column]
                if not value or form_name is None:
                    continue
                try:
                    converted[form_name] = self._convert(how, probe.fields.get(form_name), value, cells)
                except ValueError as exc:
                    row.errors.append(f"{column} “{value}” {exc}")
            if "city" in converted and converted["city"] is None:
                # Not in the catalogue: keep it as a typed place (staff can link it later).
                converted.pop("city")
                converted.setdefault("location_text" if self.kind == "event" else "suggested_location", cells["city"])
            if row.errors:
                row.action = "error"
                continue
            try:
                instance = self._existing(cells, converted)
            except ValueError as exc:
                row.action, row.errors = "error", [str(exc)]
                continue
            key = self._match_key(cells, converted)
            if key in seen:
                row.action, row.errors = "error", [f"same item as row {seen[key]}"]
                continue
            seen[key] = number

            if instance is not None:
                converted["name"] = instance.name  # matched ignoring capitals; keep the existing spelling
            data = self._base_data(instance)
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
        fields = {f.name for f in self.spec.model._meta.get_fields()}
        with transaction.atomic():
            for row in self.rows:
                if row.action == "error":
                    continue
                obj = row.form.save(commit=False)
                if row.instance is None:
                    obj.approval_status = APPROVED
                    obj.submitted_by, obj.submitted_at = user, now
                    obj.reviewed_by, obj.reviewed_at = user, now
                    if "created_by" in fields:
                        obj.created_by = user
                    if self.kind == "activity":
                        obj.visibility, obj.source = "public", "import"
                obj.save()
                row.form.save_m2m()
                done.append((row, obj))
        return done
