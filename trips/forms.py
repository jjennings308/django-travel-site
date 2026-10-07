"""Admin forms that encode rules the raw model fields cannot.

``TransportLegAdminForm`` accepts times the way a traveler thinks about them.
Leg times are stored in UTC, but nobody plans a trip in UTC, so the form takes
a *local* wall-clock time plus an IANA zone and derives the UTC value on save.

The conversion is deliberately forgiving about input format (people type
``1/15/2026 6:00 PM``, ``2026-01-15 18:00``, or ``2026-01-15T18:00:00Z``) but
strict about the thing that actually matters: a value carrying an explicit
offset is trusted as-is and never re-converted.

``DayAdminForm`` guards a per-day roster from naming someone who is not on the
trip — see the class docstring.
"""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from django import forms
from django.db import models
from django.forms.formsets import formset_factory
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone as django_timezone

from .models import (
    BookingTask,
    Comment,
    Confirmation,
    Contact,
    Day,
    Lodging,
    Meal,
    RewardsMembership,
    Section,
    Traveler,
    TransportLeg,
    Trip,
    format_local_date,
    format_local_time,
    localize,
    validate_timezone_name,
)

# Ordered: first match wins. The two 12-hour forms come last so a European
# 24-hour reading is never mistaken for one.
DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M",
    "%d %b %Y %H:%M",
    "%Y-%m-%d %I:%M %p",
    "%Y-%m-%d %I:%M%p",
    "%m/%d/%Y, %I:%M %p",
    "%b %d, %Y %I:%M %p",
)


def _timezone_choices():
    """All IANA zone names for the dropdown.

    Sourced from the stdlib rather than Django because Django 6.1's
    ``get_fixed_timezones()`` no longer exists (and ``get_fixed_timezone()``
    now takes a numeric offset, not a name).
    """
    return [("", "---------")] + sorted(
        (name, name) for name in available_timezones()
    )


class LocalDateTimeField(forms.Field):
    """A local wall-clock datetime, parsed leniently.

    Returns a ``datetime`` that is aware only when the text carried its own
    offset. This is *not* ``forms.DateTimeField``: that one normalizes aware
    input to ``settings.TIME_ZONE``, which would silently discard the
    offset the user typed in.
    """

    widget = forms.TextInput(
        attrs={"placeholder": "2026-01-15 6:00 PM", "size": 24, "autocomplete": "off"}
    )
    default_error_messages = {
        "invalid": "Enter a date and time, e.g. “2026-01-15 6:00 PM”.",
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.widget.attrs.setdefault("placeholder", "2026-01-15 6:00 PM")

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None

        # An explicit offset (Z, +02:00) is authoritative: keep it as aware
        # and let the form skip zone conversion.
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed

        for fmt in DATETIME_FORMATS:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        raise forms.ValidationError(
            self.error_messages["invalid"], code="invalid"
        )

    def prepare_value(self, value):
        """Render an existing UTC value as editable local text."""
        if value in self.empty_values or not isinstance(value, datetime):
            return value
        local = django_timezone.localtime(value, django_timezone.UTC)
        return local.strftime("%Y-%m-%d %H:%M")


class BlankOrderFallbackMixin:
    """Make an optional `order` fall back to the model default, not to NULL.

    Every model with an `order` column stores it NOT NULL with a default, and
    none of them are `blank=True`, so a plain `ModelForm` makes the field
    required and the reader has to type a sort number to add a meal.

    Setting `required = False` is only half the fix. A blank `<input
    type="number">` posts an *empty string* — that is what a browser does, every
    time, not just occasionally — and `forms.IntegerField` turns `""` into
    `None`, which `construct_instance` then writes straight through as NULL.
    The database rejects it and the save 500s.

    So the fallback is done explicitly here: a blank order becomes the model's
    own default, read from the field rather than hard-coded, so the two cannot
    drift apart.
    """

    order_field = "order"

    def clean(self):
        cleaned_data = super().clean()
        name = self.order_field
        if cleaned_data.get(name) is None:
            cleaned_data[name] = self._order_default()
        return cleaned_data

    def _order_default(self):
        model_field = self._meta.model._meta.get_field(self.order_field)
        return model_field.default if model_field.has_default() else 0


def validate_day_roster(trip, chosen):
    """Reject a day roster that names somebody who is not on the trip.

    ``Day.travelers`` is a multi-select, so nothing stops a day from claiming a
    traveler who is not on its trip. That is almost always a slip — picking a
    name off the wrong trip, or a traveler who was removed from the trip
    afterwards — and it leaves a day whose roster contradicting the trip it
    belongs to. Blank is always fine; that means the whole group is together.

    Shared by the admin form and the app's rather than written twice: a day that
    contradicts its trip is wrong in the admin and wrong on a web page, and two
    copies of this rule would eventually disagree about which.

    The app forms *also* narrow the choice list to the trip's own travelers, so
    a bad value is not selectable there at all. This stays as the backstop that
    catches a roster which was valid when saved and stopped being valid later.
    """
    if trip is None or not chosen:
        return
    on_trip = set(trip.travelers.values_list("pk", flat=True))
    strangers = sorted(
        traveler.name for traveler in chosen if traveler.pk not in on_trip
    )
    if strangers:
        raise forms.ValidationError(
            "Not on this trip: "
            + ", ".join(strangers)
            + ". Add them to the trip's travelers first, or clear the field "
            "if the whole group is together that day."
        )


def local_to_utc(naive_local, zone_name):
    """Attach ``zone_name`` to a naive datetime and convert to UTC.

    Returns ``None`` when the zone is unusable rather than assuming UTC, so a
    blank zone is caught by validation instead of being silently wrong.
    """
    if not zone_name:
        return None
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    return naive_local.replace(tzinfo=zone).astimezone(django_timezone.UTC)


#: Zones offered as autocomplete suggestions on the app's leg form. A short
#: list on purpose: the point is to save typing "America/Denver", not to replace
#: the full list. Any valid IANA name is still accepted, because these are the
#: zones people actually travel through, not an allowlist of all 486.
COMMON_ZONE_SUGGESTIONS = (
    "America/Anchorage",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/New_York",
    "America/Sao_Paulo",
    "America/Toronto",
    "America/Vancouver",
    "Asia/Dubai",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Atlantic/Reykjavik",
    "Australia/Sydney",
    "Europe/Amsterdam",
    "Europe/Athens",
    "Europe/Berlin",
    "Europe/Dublin",
    "Europe/Lisbon",
    "Europe/London",
    "Europe/Madrid",
    "Europe/Oslo",
    "Europe/Paris",
    "Europe/Prague",
    "Europe/Rome",
    "Europe/Vienna",
    "Europe/Zurich",
    "Pacific/Auckland",
    "UTC",
)


class ZoneNameField(forms.CharField):
    """A compact IANA zone input: free text, validated, with suggestions.

    The alternative is a ``<select>`` of all 486 zones. That is fine for one
    admin inline row and unusable on a page with a row per leg: the Taos trip
    alone rendered nine such selects and 4360 of the page's 4948 ``<option>``
    elements were zone names, for a 358kb form.

    This is not a weaker check. ``validate_timezone_name`` is the same validator
    the model field uses, so a typo is still rejected rather than silently
    falling back to UTC at render time.
    """

    def __init__(self, *args, label_example="America/New_York", **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("max_length", 64)
        kwargs.setdefault(
            "help_text", f"IANA zone name, e.g. {label_example}. Leave blank for UTC."
        )
        super().__init__(*args, **kwargs)
        self.validators.append(validate_timezone_name)

    def to_python(self, value):
        # ZoneInfo lookups are case-sensitive, and people type "america/denver".
        return super().to_python(value.strip() if isinstance(value, str) else value)


class LocalLegTimeMixin:
    """Local-time entry for a transport leg, shared by the admin and app forms.

    A leg's ``departure_at`` / ``arrival_at`` are stored in UTC, but nobody plans
    a trip in UTC, so both forms take a *local* wall-clock time plus an IANA
    zone and derive the UTC value on save. The raw UTC fields are excluded from
    the form entirely, so what is stored and what is displayed cannot disagree.

    This is a mixin rather than a shared base ModelForm because the two forms
    legitimately differ — the admin has a ``trip`` field because the inline
    needs it, the app formset does not because the parent is set for it, and the
    app page shows many rows at once so it needs a lighter zone control. The
    *conversion* is the part that must not be written twice: if the two ever
    disagreed, a leg entered in the app and one entered in the admin would store
    different values for the same displayed time.

    Subclasses pick their own zone control by overriding :meth:`zone_field`;
    ``declared_fields`` is rebuilt per subclass in ``__init_subclass__`` so
    that override is actually used. Building it once in the class body would
    bind the base class's version to both.
    """

    #: Set on forms whose zone inputs should be fed suggestions in the template.
    suggest_zones = False

    @staticmethod
    def zone_field(label_example):
        """The zone control. Overridden where a full dropdown is too heavy."""
        return forms.ChoiceField(
            choices=_timezone_choices(),
            required=False,
            help_text=f"IANA zone for this end, e.g. {label_example}",
        )

    @classmethod
    def local_time_fields(cls):
        return {
            "origin_timezone": cls.zone_field("America/New_York"),
            "destination_timezone": cls.zone_field("America/Denver"),
            "departure_local": LocalDateTimeField(
                required=True,
                label="Departure (local)",
                help_text="Wall-clock time at the origin. Converted to UTC on save.",
            ),
            "arrival_local": LocalDateTimeField(
                required=True,
                label="Arrival (local)",
                help_text="Wall-clock time at the destination. Converted to UTC on save.",
            ),
        }

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # DeclaredFieldsMetaclass only collects `declared_fields` from bases, so
        # a plain mixin holding Field attributes is invisible to it and the
        # ModelForm fails with "Unknown field(s) (arrival_local, ...)".
        # Assigning here, per subclass, is both what the metaclass looks for and
        # what lets `zone_field` be overridden.
        cls.declared_fields = cls.local_time_fields()

    @staticmethod
    def _local_text(value, zone_name):
        local = localize(value, zone_name)
        if local is None:
            return None
        return local.strftime("%Y-%m-%d %H:%M")

    def seed_local_time_initial(self):
        """Show an existing leg's times as local text, the way they are read.

        Without this the field opens blank on a leg that already has a departure
        set, and re-saving would have to retype it.
        """
        if not self.instance.pk:
            return
        self.fields["departure_local"].initial = self._local_text(
            self.instance.departure_at, self.instance.origin_timezone
        )
        self.fields["arrival_local"].initial = self._local_text(
            self.instance.arrival_at, self.instance.destination_timezone
        )

    def _resolve(self, raw, zone_name, zone_field_name, field_name, label):
        """Turn one local input into an aware UTC datetime."""
        if raw is None:
            return self.instance.__getattribute__(field_name)

        if django_timezone.is_aware(raw):
            # Typed with its own offset — trust it, ignore the zone dropdown.
            return raw.astimezone(django_timezone.UTC)

        if not zone_name:
            self.add_error(
                zone_field_name,
                f"{label} needs a timezone to convert from, since no offset "
                f"was included in the time.",
            )
            return None

        try:
            converted = local_to_utc(raw, zone_name)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            self.add_error(
                zone_field_name, f"{zone_name!r} is not a valid timezone."
            )
            return None

        if converted is None:
            self.add_error(zone_field_name, "Choose a timezone to convert from.")
            return None
        return converted

    def clean_local_leg_times(self):
        """Derive the UTC fields and check the leg does not run backwards."""
        # Convert even when another field has an error: the model-level
        # validation that runs after this needs real datetimes, and skipping
        # would report a misleading "cannot be null" on top of the real
        # error. Per-field errors are still collected via add_error.
        departure = self._resolve(
            self.cleaned_data.get("departure_local"),
            self.cleaned_data.get("origin_timezone"),
            "origin_timezone",
            "departure_at",
            "Departure",
        )
        arrival = self._resolve(
            self.cleaned_data.get("arrival_local"),
            self.cleaned_data.get("destination_timezone"),
            "destination_timezone",
            "arrival_at",
            "Arrival",
        )

        if departure is not None:
            self.instance.departure_at = departure
        if arrival is not None:
            self.instance.arrival_at = arrival

        if departure and arrival and arrival < departure:
            self.add_error(
                "arrival_local",
                "Arrival is before departure. Check the local times and zones "
                "— a leg arriving “the same day” locally can still be next "
                "day in UTC.",
            )
        return self.cleaned_data


class TransportLegAdminForm(LocalLegTimeMixin, forms.ModelForm):
    """Admin inline form for a transport leg. See ``LocalLegTimeMixin``."""

    class Meta:
        model = TransportLeg
        fields = [
            "trip",
            "mode",
            "operator",
            "service_number",
            "confirmation_number",
            "origin",
            "destination",
            "departure_local",
            "origin_timezone",
            "arrival_local",
            "destination_timezone",
            "cost",
            "currency",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The model default is "USD", so don't force the admin to retype it.
        self.fields["currency"].required = False
        self.seed_local_time_initial()

    def clean(self):
        cleaned_data = super().clean()
        self.clean_local_leg_times()
        return cleaned_data


class DayAdminForm(forms.ModelForm):
    """Edit a day, rejecting a roster that names someone not on the trip.

    ``Day.travelers`` is a free-form multi-select, so nothing stops a day from
    claiming a traveler who is not actually on the trip. That is almost always
    a slip — picking a name off the wrong trip, or a traveler who was removed
    from the trip afterwards — and it produces a day whose roster contradicts
    the trip it belongs to. Blank is always fine; that means the whole group.
    """

    class Meta:
        model = Day
        fields = [
            "trip",
            "day_number",
            "date",
            "theme",
            "meals_included",
            "travelers",
        ]

    def clean(self):
        cleaned_data = super().clean()
        validate_day_roster(cleaned_data.get("trip"), cleaned_data.get("travelers"))
        return cleaned_data


# ---------------------------------------------------------------------------
# Forms for the app's own editing views
#
# Above this line are the two forms the admin uses, which predate the editing
# views and are named for that. The forms below are the ones the CRUD views
# render. They deliberately do not reuse the admin forms by inheritance: an
# admin form is shaped by what the inline needs to show, and these are shaped
# by what one person editing one trip needs. The shared pieces that *are*
# genuinely shared — LocalDateTimeField and the roster rule — are shared by
# composition instead.
# ---------------------------------------------------------------------------


class TripForm(forms.ModelForm):
    """Create or edit a trip.

    ``created_by`` and ``deleted_at`` are not fields. Ownership is set by the
    view from the session and is not something a form should be able to
    overwrite, and deletion is a separate action with its own confirmation.
    """

    def __init__(self, *args, **kwargs):
        # A ModelForm does not pick the model's field defaults up as initial:
        # BaseModelForm.__init__ builds its own object_data (empty when there is
        # no instance) and Form.__init__ assigns straight over self.initial, so
        # a class-level `initial = {...}` is silently discarded. It has to be
        # passed through the constructor instead, or the status select opens on
        # its first blank choice and the reader has to choose a planning stage
        # before a new trip can be saved.
        initial = {"status": Trip.Status.STARTING}
        initial.update(kwargs.get("initial") or {})
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    class Meta:
        model = Trip
        fields = (
            "name",
            "destination",
            "start_date",
            "end_date",
            "travelers",
            "budget",
            "structure",
            "status",
            "notes",
        )
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 5}),
            # A plain multi-select is a worse control than a checkbox list but
            # it is the one that works without JavaScript, and the traveler
            # count is small enough that it stays readable.
            "travelers": forms.SelectMultiple(attrs={"size": 6}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")
        # Not a model constraint: the admin has never enforced it either, and
        # an end before the start is nonsense that renders as a negative
        # number of nights once it reaches the page.
        if start and end and end < start:
            self.add_error(
                "end_date",
                "The end date cannot be before the start date.",
            )
        return cleaned_data


class AddTravelerForm(forms.Form):
    """Add a traveler by name, from the trip form.

    A plain ``Form``, not a ``ModelForm``, and deliberately *not* a field called
    ``name``: this form is bound to the same POST data as ``TripForm``, which
    has a ``name`` field of its own. A ModelForm here would read the trip's
    name out of the shared payload and create a traveler called after the trip.

    Traveler rows are a shared roster — one person can be on several trips — so
    this is the only place the app creates one, and it deliberately does not
    offer to edit an existing traveler. Renaming somebody from inside one trip's
    form would silently change every other trip they appear on.
    """

    new_traveler_name = forms.CharField(
        required=False,
        label="Name",
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "off"}),
    )

    def clean_new_traveler_name(self):
        # Normalise before it is used as a key. "Ada " and "Ada" are the same
        # person, and a trailing space is exactly how a duplicate roster row
        # gets created by accident.
        return self.cleaned_data["new_traveler_name"].strip()


# ---------------------------------------------------------------------------
# Subsection formsets
#
# The trip-level lists on the edit page: lodging, transport, confirmations,
# contacts and booking tasks. They are formsets rather than separate pages so a
# person adding a hotel and its confirmation number does it in one submit, which
# is how the two are actually entered.
#
# Days are deliberately *not* here. A day owns meals and sections, so it is its
# own page with its own formsets; see DayFormSet usage in views.py.
# ---------------------------------------------------------------------------


class LodgingForm(forms.ModelForm):
    """One place to stay. Check-out has to follow check-in."""

    class Meta:
        model = Lodging
        fields = [
            "name",
            "address",
            "check_in",
            "check_out",
            "confirmation_number",
            "nightly_rate",
            "currency",
            "notes",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # "USD" is the model default; make the admin-type-please not type it.
        self.fields["currency"].required = False

    def clean(self):
        cleaned_data = super().clean()
        check_in = cleaned_data.get("check_in")
        check_out = cleaned_data.get("check_out")
        if check_in and check_out and check_out < check_in:
            self.add_error("check_out", "Check-out cannot be before check-in.")
        return cleaned_data


class TransportLegForm(LocalLegTimeMixin, forms.ModelForm):
    """One transport leg, entered by local times like the admin inline.

    Same conversion as the admin — see ``LocalLegTimeMixin``. Two deliberate
    differences:

    * ``trip`` is absent, because a formset sets the parent itself and exposing
      it would let a post point a leg at a different trip.
    * Zones are free text with suggestions rather than a dropdown of all 486.
      This form is rendered once per leg on one page, and nine full zone selects
      made the Taos edit form 358kb — see ``ZoneNameField``.
    """

    suggest_zones = True

    @staticmethod
    def zone_field(label_example):
        return ZoneNameField(label_example=label_example)

    class Meta:
        model = TransportLeg
        fields = [
            "mode",
            "origin",
            "origin_timezone",
            "departure_local",
            "destination",
            "destination_timezone",
            "arrival_local",
            "operator",
            "service_number",
            "confirmation_number",
            "cost",
            "currency",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # "USD" is the model default; don't make somebody retype it.
        self.fields["currency"].required = False
        # Point the zone inputs at the datalist the formset renders once. The
        # id has to match `ZoneSuggestingFormSet`'s prefix.
        for name in ("origin_timezone", "destination_timezone"):
            self.fields[name].widget.attrs["list"] = "transport-zone-suggestions"
            self.fields[name].widget.attrs["placeholder"] = "America/Denver"
        self.seed_local_time_initial()

    def clean(self):
        cleaned_data = super().clean()
        self.clean_local_leg_times()
        return cleaned_data


class ConfirmationForm(forms.ModelForm):
    """One booking reference for the Quick Reference section."""

    class Meta:
        model = Confirmation
        fields = ["label", "confirmation_number", "provider", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class ContactForm(forms.ModelForm):
    """One person or business the travelers may need to reach."""

    class Meta:
        model = Contact
        fields = ["name", "role", "phone", "email", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class BookingTaskForm(BlankOrderFallbackMixin, forms.ModelForm):
    """One outstanding booking, decision or confirmation.

    ``day`` and ``confirmation`` are both optional and both SET_NULL on the
    model, so deleting the thing a task pointed at drops the link rather than the
    task. That is why neither is required here.
    """

    class Meta:
        model = BookingTask
        fields = [
            "title",
            "priority",
            "due",
            "due_note",
            "day",
            "confirmation",
            "done",
            "order",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # `order` has a model default of 0 but is not blank, so a ModelForm
        # would make it a *required* field — asking somebody to type 0 into a
        # sort column to save a booking task. Left blank it falls back to the
        # model default, because an omitted value skips the field entirely
        # rather than storing an empty string.
        self.fields["order"].required = False


class TripScopedFormSet(BaseInlineFormSet):
    """An inline formset whose cross-trip choices are limited to its own trip.

    ``BookingTask`` can point at a ``Day`` and a ``Confirmation``. Both of those
    belong to a trip, and neither field can simply be trusted: a hand-written
    POST naming another trip's day would otherwise attach this trip's booking
    task to it, and the task would then show up in the *other* trip's list.

    Narrowing the querysets here — rather than validating after the fact — means
    the wrong value is not a selectable choice at all, so the browser and a curl
    request are rejected the same way.

    Note the ordering consequence: a confirmation created in the *same* submit
    cannot be picked by a task in that submit, because the choice list is read
    before anything is written. Link it on a second save. The reverse is fine —
    an existing confirmation can be named immediately.
    """

    #: Form field names to narrow to the parent trip's own rows.
    trip_scoped_fields = ()

    def __init__(self, data=None, files=None, instance=None, **kwargs):
        super().__init__(data, files, instance=instance, **kwargs)
        if instance is None:
            return
        for form in self.forms:
            for field_name in self.trip_scoped_fields:
                field = form.fields.get(field_name)
                if field is None:
                    continue
                field.queryset = field.queryset.filter(trip=instance)


class ScopedBookingTaskFormSet(TripScopedFormSet):
    """The one formset with cross-trip choices to narrow."""

    trip_scoped_fields = ("day", "confirmation")


LodgingFormSet = inlineformset_factory(
    Trip, Lodging, form=LodgingForm, extra=1, can_delete=True
)
class ZoneSuggestingFormSet(BaseInlineFormSet):
    """A formset that ships a shared datalist of common zone names.

    Rendered once per section rather than once per row, so the page does not
    repeat the list for every leg. The inputs point at it by id.
    """

    zone_suggestions = COMMON_ZONE_SUGGESTIONS


TransportLegFormSet = inlineformset_factory(
    Trip,
    TransportLeg,
    form=TransportLegForm,
    formset=ZoneSuggestingFormSet,
    extra=1,
    can_delete=True,
)
ConfirmationFormSet = inlineformset_factory(
    Trip, Confirmation, form=ConfirmationForm, extra=1, can_delete=True
)
ContactFormSet = inlineformset_factory(
    Trip, Contact, form=ContactForm, extra=1, can_delete=True
)
BookingTaskFormSet = inlineformset_factory(
    Trip,
    BookingTask,
    form=BookingTaskForm,
    formset=ScopedBookingTaskFormSet,
    extra=1,
    can_delete=True,
)

#: Formset prefixes, in the order the edit page renders them. The key is the
#: ``prefix`` the formset is bound under, so it is also the POST key prefix —
#: ``lodging-0-name`` and friends.
TRIP_SUBSECTION_FORMSETS = (
    ("lodging", "Lodging", LodgingFormSet),
    ("transport", "Transport", TransportLegFormSet),
    ("confirmations", "Confirmations", ConfirmationFormSet),
    ("contacts", "Contacts", ContactFormSet),
    ("booking_tasks", "Booking tasks", BookingTaskFormSet),
)


def trip_subsection_formsets(trip, data=None):
    """Build the trip-level formsets in page order.

    Returns ``(key, label, formset)`` triples so the view and the template agree
    on the names without either hardcoding the list.

    ``extra=1`` gives one blank row to fill in. An untouched blank row is skipped
    by Django rather than saved as a row of NULLs, so it costs the user nothing.
    """
    return [
        (key, label, formset_cls(data=data, instance=trip, prefix=key))
        for key, label, formset_cls in TRIP_SUBSECTION_FORMSETS
    ]


# ---------------------------------------------------------------------------
# Per-day forms
#
# A day owns its meals and sections, so it gets its own pages rather than more
# tables on the trip edit page. The trip is passed in rather than exposed as a
# form field: a ``day`` field here would be a value a post could point at a
# different trip, exactly like the formset's parent FK that is never rendered.
# ---------------------------------------------------------------------------


class DayForm(forms.ModelForm):
    """One day of a trip.

    Blank ``travelers`` means the whole group is together, which is the common
    case and needs no input — that is why the field is not required. The choice
    list is narrowed to the trip's own travelers so a roster naming a stranger
    is not selectable at all.
    """

    class Meta:
        model = Day
        fields = ["day_number", "date", "theme", "meals_included", "travelers"]
        widgets = {
            "travelers": forms.SelectMultiple(attrs={"size": 6}),
        }

    def __init__(self, *args, trip=None, **kwargs):
        super().__init__(*args, **kwargs)
        if trip is None:
            return
        self.trip = trip
        if "travelers" in self.fields:
            self.fields["travelers"].queryset = trip.travelers.all()
        # Prefill the next free day number: a new day is nearly always the next
        # one, and the unique constraint on (trip, day_number) would otherwise
        # make the first thing to do a guess. `date` is deliberately left alone —
        # a wrong prefill is a wrong date nobody notices, and this field is
        # never required.
        if not self.instance.pk and not self.is_bound:
            last = (
                trip.days.aggregate(models.Max("day_number"))["day_number__max"] or 0
            )
            self.fields["day_number"].initial = last + 1

    def clean(self):
        cleaned_data = super().clean()
        trip = getattr(self, "trip", None)
        validate_day_roster(trip, cleaned_data.get("travelers"))

        # Checked by hand rather than left to the model. `BaseModelForm
        # ._post_clean` calls `full_clean(validate_unique=False)`, so a
        # ModelForm never enforces `unique_together` — and `trip` is not even
        # assigned to the instance until after validation, so the model could
        # not match a row even if it were asked to. Without this, posting a
        # day number that already exists is a 500 from the database rather than
        # an error on the field.
        number = cleaned_data.get("day_number")
        if trip is not None and number is not None:
            clash = Day.objects.filter(trip=trip, day_number=number)
            if self.instance.pk:
                # Re-saving a day without changing its number is not a clash.
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error(
                    "day_number", f"Day {number} already exists on this trip."
                )
        return cleaned_data


class MealForm(BlankOrderFallbackMixin, forms.ModelForm):
    """One restaurant or food stop on a day."""

    class Meta:
        model = Meal
        fields = [
            "name",
            "meal_type",
            "cuisine",
            "price_range",
            "why_recommended",
            "reservation_notes",
            "order",
        ]
        widgets = {
            "why_recommended": forms.Textarea(attrs={"rows": 2}),
            "reservation_notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].required = False
        # price_range is blank=True on the model ("" for "no band"), so an
        # unset meal is not forced to invent a price.
        self.fields["price_range"].required = False


MealFormSet = inlineformset_factory(
    Day, Meal, form=MealForm, extra=1, can_delete=True
)

#: Meal formset prefix, and so the POST key prefix: ``meals-0-name``.
MEAL_FORMSET_PREFIX = "meals"


# ---------------------------------------------------------------------------
# Section payloads
#
# `Section.content` is a JSON blob whose shape varies by `section_type`, so one
# form cannot validate it — and it must not. A logistics table's `rows` are a
# list of lists; a callout's `text` is a string; a phase's `highlights` is a list
# of strings. Validating all of them at once would mean either rejecting shapes
# that are legitimate for some type, or accepting anything and calling it
# validation.
#
# So there is one form per type, chosen by `section_type`, and each knows both
# how to read its payload out of the JSON and how to write itself back.
#
# Every one of them is a plain `Form`, not a `ModelForm`. `content` is the field
# being edited, and going through the model would mean a `clean_content()` that
# has to guess the type, which is the thing being avoided here.
# ---------------------------------------------------------------------------


class PayloadForm(forms.Form):
    """Base for the per-type payload editors.

    Subclasses declare ``fields`` and implement ``to_content()``. The base owns
    the part that is easy to get wrong: turning the stored JSON into initial
    values and back again, losslessly.

    **Round-tripping is the point.** `content` is written by importers that know
    more than the UI does, so it can legitimately carry keys no form here has a
    field for — a `note`, a `booking_url`, a field added by a later parser. A
    form that rebuilt the dict from its own fields would silently drop those on
    the first save, so ``to_content`` starts from the stored dict and overwrites
    only the keys it actually manages.
    """

    #: Keys this form reads and writes. Anything else in `content` is preserved
    #: untouched, which is what makes editing a section safe.
    payload_keys: tuple = ()

    def __init__(self, *args, content=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.stored = dict(content or {})
        if not self.is_bound:
            for name, value in self.initial_from_content(self.stored).items():
                self.initial.setdefault(name, value)

    def initial_from_content(self, content):
        """Map stored JSON onto initial values. Subclasses override."""
        return {}

    def to_content(self):
        """Build the new payload: stored keys preserved, managed keys replaced."""
        content = dict(self.stored)
        content.update(self.managed_content())
        return content

    def managed_content(self):
        """The payload built from the form's cleaned data. Subclasses override."""
        return {}


def _lines_to_list(raw):
    """One item per line, blanks dropped.

    Blank interior lines are dropped rather than becoming empty bullets: a stray
    newline is a formatting slip, and an empty `<li>` in the detail page is a
    visible artifact that the reader cannot tell was ever meant to be there.
    Trailing whitespace is stripped from each item.
    """
    return [line.strip() for line in (raw or "").splitlines() if line.strip()]


def _list_payload(content, key, value):
    """Set a list-valued payload key without inventing one.

    If the key was already stored it is always written, even when the list is now
    empty — the reader cleared it, and leaving the old rows behind would be
    worse than storing `[]`.

    If the key was *not* stored and the list is empty it is left absent. The
    importers omit optional keys when there is nothing to put in them, so writing
    `"highlights": []` would change the payload of a section nobody edited.
    """
    if key in content or value:
        content[key] = value
    return content


def _list_to_lines(items):
    return "\n".join(items or [])


#: Cells within a logistics-table row are separated by this. Chosen because it is
#: typeable; a tab would be the spreadsheet convention but is invisible in a
#: textarea and effectively impossible to enter by hand with no JavaScript to
#: build the row for you. No cell in the imported data contains one.
ROW_CELL_SEPARATOR = "|"


class PhasePayloadForm(PayloadForm):
    heading = forms.CharField(max_length=255)
    summary = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3}), required=False
    )
    highlights = forms.CharField(
        label="Highlights",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="One per line. Leave blank if this phase has none.",
    )

    payload_keys = ("heading", "summary", "highlights")

    def initial_from_content(self, content):
        return {
            "heading": content.get("heading", ""),
            "summary": content.get("summary", ""),
            "highlights": _list_to_lines(content.get("highlights")),
        }

    def managed_content(self):
        return _list_payload(
            {
                "heading": self.cleaned_data["heading"],
                "summary": self.cleaned_data["summary"],
            },
            "highlights",
            _lines_to_list(self.cleaned_data["highlights"]),
        )


class CalloutPayloadForm(PayloadForm):
    TONES = (
        ("info", "Info"),
        ("warning", "Warning"),
        ("critical", "Critical"),
    )
    tone = forms.ChoiceField(choices=TONES)
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))

    payload_keys = ("tone", "text")

    def initial_from_content(self, content):
        return {
            "tone": content.get("tone", "info"),
            "text": content.get("text", ""),
        }

    def managed_content(self):
        return {
            "tone": self.cleaned_data["tone"],
            "text": self.cleaned_data["text"],
        }


class FreeTextPayloadForm(PayloadForm):
    paragraphs = forms.CharField(
        label="Paragraphs",
        widget=forms.Textarea(attrs={"rows": 10}),
        help_text="One paragraph per line. Blank lines are ignored.",
    )

    payload_keys = ("paragraphs",)

    def initial_from_content(self, content):
        return {"paragraphs": _list_to_lines(content.get("paragraphs"))}

    def managed_content(self):
        return _list_payload(
            {}, "paragraphs", _lines_to_list(self.cleaned_data["paragraphs"])
        )


class LogisticsTablePayloadForm(PayloadForm):
    """The two-list table: ``columns`` then ``rows``.

    A table is the one payload that genuinely does not fit a fixed set of form
    fields, because its width varies — the imported data has 2-, 3- and 4-column
    tables, and the column *names* differ per table too. Rendering a column
    header per row would mean a form whose field names depend on the row, which
    is not something a POST can describe.

    So both halves are textareas with a stated format, and the row/column counts
    are checked against each other. The mismatch is caught rather than rendered:
    a logistics table whose rows are misaligned is worse than one that refused to
    save, because it looks fine and reads wrong.
    """

    columns = forms.CharField(
        label="Columns",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=(
            "One column name per line — these are the table's headers, so a "
            "rename here changes every row's header."
        ),
    )
    rows = forms.CharField(
        label="Rows",
        widget=forms.Textarea(attrs={"rows": 8}),
        help_text=(
            "One row per line, cells separated by a “|”. Every row needs "
            "exactly as many cells as there are columns."
        ),
    )

    payload_keys = ("columns", "rows")

    def initial_from_content(self, content):
        return {
            "columns": _list_to_lines(content.get("columns")),
            "rows": "\n".join(
                ROW_CELL_SEPARATOR.join(str(cell) for cell in row)
                for row in content.get("rows") or []
            ),
        }

    def managed_content(self):
        columns = _lines_to_list(self.cleaned_data["columns"])
        rows = [
            [cell.strip() for cell in line.split(ROW_CELL_SEPARATOR)]
            for line in (self.cleaned_data["rows"] or "").splitlines()
            if line.strip()
        ]
        return _list_payload({"columns": columns}, "rows", rows)

    def clean(self):
        cleaned_data = super().clean()
        columns = _lines_to_list(cleaned_data.get("columns"))
        raw_rows = cleaned_data.get("rows") or ""

        # Report per row, naming the row number, because "one of your rows is
        # wrong" is not actionable when there are thirty of them.
        for index, line in enumerate(raw_rows.splitlines(), start=1):
            if not line.strip():
                continue
            count = len(line.split(ROW_CELL_SEPARATOR))
            if count != len(columns):
                self.add_error(
                    "rows",
                    f"Row {index} has {count} cell(s) but the table has "
                    f"{len(columns)} column(s). Separate every cell with "
                    f"“{ROW_CELL_SEPARATOR}”.",
                )
        return cleaned_data


class AdventureOptionForm(forms.Form):
    """One of the interchangeable options in a ``choose_your_adventure``.

    ``letter`` is a real key in the imported data (options are labelled A, B, C)
    and is not in the module docstring's shape, which is why the option keys are
    read off the data rather than assumed.
    """

    letter = forms.CharField(max_length=8, required=False)
    title = forms.CharField(max_length=255)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))
    duration = forms.CharField(max_length=64, required=False)
    cost = forms.CharField(max_length=64, required=False)

    #: Keys this form owns. Anything else in a stored option is preserved.
    option_keys = ("letter", "title", "description", "duration", "cost")


AdventureOptionFormSet = formset_factory(
    AdventureOptionForm, extra=1, can_delete=True
)


class ChooseYourAdventurePayloadForm(PayloadForm):
    """``prompt`` plus a formset of ``options``.

    Options are a list of dicts, which is the one payload a textarea cannot
    express without making the reader write JSON by hand. So this is a real
    formset over plain forms — no model, since options live inside the blob
    rather than in a table.

    Per-option unknown keys are preserved by index: stored option *i* is merged
    with submitted option *i*, keeping any key `AdventureOptionForm` has no field
    for. Index alignment holds because the formset renders one form per stored
    option, in order, and a deletion removes the row from both sides at once.
    """

    prompt = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}))

    payload_keys = ("prompt", "options")

    def __init__(self, *args, content=None, **kwargs):
        super().__init__(*args, content=content, **kwargs)
        stored_options = (self.stored or {}).get("options") or []

        if self.is_bound:
            self.options = AdventureOptionFormSet(self.data, prefix="options")
        else:
            initial = [
                {
                    "letter": option.get("letter", ""),
                    "title": option.get("title", ""),
                    "description": option.get("description", ""),
                    "duration": option.get("duration", ""),
                    "cost": option.get("cost", ""),
                }
                for option in stored_options
                if isinstance(option, dict)
            ]
            # One blank row to fill, not one *per* stored option — `extra=1` is
            # set by the factory, and it is the no-JavaScript convention the
            # rest of this app uses.
            self.options = AdventureOptionFormSet(
                initial=initial, prefix="options"
            )

    def initial_from_content(self, content):
        return {"prompt": content.get("prompt", "")}

    def clean(self):
        cleaned_data = super().clean()
        if not self.options.is_valid():
            for error in self.options.non_form_errors():
                self.add_error(None, error)
            if any(option.errors for option in self.options.forms):
                # An invalid option has to invalidate the *section*. It used not
                # to: only `non_form_errors` came across, so a half-typed option
                # (`letter` and `description`, no `title`) validated fine and was
                # then written to `content` missing its title. The save looked
                # like it worked, which is the worst way for this to fail — the
                # template already renders each option's errors inline, so all
                # that is needed here is for the outer form to agree.
                #
                # Django's `extra` row is built with `empty_permitted=True`, so
                # the untouched blank row at the bottom stays valid and is still
                # skipped on save rather than blocking the whole form.
                self.add_error(None, "Fix the highlighted options.")
        return cleaned_data

    def managed_content(self):
        options = []
        stored_options = [
            option
            for option in (self.stored or {}).get("options") or []
            if isinstance(option, dict)
        ]
        for index, form in enumerate(self.options.forms):
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            managed = {
                key: form.cleaned_data.get(key, "") or ""
                for key in AdventureOptionForm.option_keys
            }
            # The untouched blank row `extra=1` leaves is not an option. Skipping
            # it is the same rule the inline formsets use: without it, opening a
            # section and saving it unchanged appends an empty option.
            if not any(managed.values()):
                continue
            # Merge over the stored option at the same index, so a key this form
            # has no field for survives the save.
            option = dict(stored_options[index]) if index < len(stored_options) else {}
            option.update(managed)
            # Drop the keys *this form* owns that are now empty, so clearing a
            # `cost` removes it rather than storing `"cost": ""` forever. Keys
            # merged in from storage are left alone: an empty value there was put
            # there deliberately and is none of this form's business.
            options.append(
                {
                    key: value
                    for key, value in option.items()
                    if key not in managed or value != ""
                }
            )
        return _list_payload(
            {"prompt": self.cleaned_data["prompt"]}, "options", options
        )


#: `section_type` -> payload form. The one place that knows the mapping, so the
#: views and the templates cannot disagree about which form edits which type.
SECTION_PAYLOAD_FORMS = {
    Section.Type.PHASE: PhasePayloadForm,
    Section.Type.LOGISTICS_TABLE: LogisticsTablePayloadForm,
    Section.Type.CALLOUT: CalloutPayloadForm,
    Section.Type.CHOOSE_YOUR_ADVENTURE: ChooseYourAdventurePayloadForm,
    Section.Type.FREE_TEXT: FreeTextPayloadForm,
}


def section_payload_form(section_type, *args, content=None, **kwargs):
    """Build the payload form for a section type, or None if it is unknown.

    Returning ``None`` for an unrecognised type is what lets the app stay useful
    against content the importers wrote ahead of it: the row is readable and
    reportable as uneditable rather than a 500 from a missing dict key.
    """
    form_class = SECTION_PAYLOAD_FORMS.get(section_type)
    if form_class is None:
        return None
    return form_class(*args, content=content, **kwargs)


class SectionForm(BlankOrderFallbackMixin, forms.ModelForm):
    """The relational half of a ``Section``: title, icon, order.

    ``section_type`` and ``content`` are deliberately absent. The type is chosen
    once, when the section is created, because the payload form is chosen from
    it and changing it later would mean reinterpreting the payload; and the
    payload is edited by the type-specific form, not here.

    Excluding ``content`` also keeps this form from writing it. A
    ``ModelForm`` with ``content`` in ``fields`` would save the instance's
    current value, which is correct today and quietly wrong the first time
    someone edits the title of a section whose payload came from a parser.
    """

    class Meta:
        model = Section
        fields = ["title", "icon", "order"]
        widgets = {
            "icon": forms.TextInput(
                attrs={"placeholder": "emoji or short label", "autocomplete": "off"}
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["order"].required = False


class CommentForm(forms.ModelForm):
    """The body of a comment.

    Only ``body``. ``author`` comes from the session and ``content_type`` /
    ``object_id`` from the URL, so neither is a field here — a form field for the
    target would be a value to trust, and a hand-written POST could then attach
    a comment to a trip the poster cannot see.
    """

    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Add a note for the group",
                }
            )
        }

    def __init__(self, *args, **kwargs):
        self.target = kwargs.pop("target", None)
        super().__init__(*args, **kwargs)
        self.fields["body"].widget.attrs.setdefault("rows", 4)
        # Not required, so that ``clean_body`` is the thing that reports an empty
        # comment. A required field strips its value before ``clean_<field>`` ever
        # runs, so whitespace-only text would come back as Django's generic "This
        # field is required" rather than saying what is actually wrong.
        self.fields["body"].required = False

    def clean_body(self):
        """Reject whitespace-only text.

        ``Model.save`` strips the body, so without this a comment of " " would
        pass validation and save as an empty row that renders as nothing. A
        comment with no words in it is a mis-click, not a comment.
        """
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Write something first.")
        return body

    def save(self, commit=True, *, author=None, target=None):
        """Attach the comment, then save.

        The target is a keyword argument rather than form data on purpose: it
        comes from the URL, resolved by the view through the same visibility
        check as reading the thing being commented on.
        """
        comment = super().save(commit=False)
        if author is not None:
            comment.author = author
        target = target if target is not None else self.target
        if target is not None:
            comment.content_object = target
        if commit:
            comment.save()
            self.save_m2m()
        return comment


# ---------------------------------------------------------------------------
# A person's own travel profile
# ---------------------------------------------------------------------------

#: An ISO date input. ``format`` is what makes a stored value show up again:
#: the browser's date control only accepts ``YYYY-MM-DD``.
ISO_DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class TravelerProfileForm(forms.ModelForm):
    """The signed-in person's own traveler row.

    ``name`` and ``user`` are not fields. The name is the roster's identity —
    renaming it renames the person on every trip they are on, which is a staff
    decision (see "Travelers and accounts" in CLAUDE.md) — and the account link
    is never something a form may set. A posted ``name`` is simply ignored.
    """

    class Meta:
        model = Traveler
        fields = (
            "seat_preference",
            "cabin_preference",
            "bed_preference",
            "meal_preference",
            "home_airport",
            "dietary_notes",
            "mobility_notes",
            "known_traveler_number",
            "redress_number",
            "passport_country",
            "passport_number",
            "passport_expires",
        )
        widgets = {
            "dietary_notes": forms.Textarea(attrs={"rows": 3}),
            "mobility_notes": forms.Textarea(attrs={"rows": 3}),
            "passport_expires": ISO_DATE_INPUT,
        }

    #: The page renders the form in these groups, so the template does not
    #: hard-code field names and a new field lands in a section by being added
    #: here.
    PREFERENCE_FIELDS = (
        "seat_preference",
        "cabin_preference",
        "bed_preference",
        "meal_preference",
        "home_airport",
        "dietary_notes",
        "mobility_notes",
    )
    DOCUMENT_FIELDS = (
        "known_traveler_number",
        "redress_number",
        "passport_country",
        "passport_number",
        "passport_expires",
    )

    def field_group(self, names):
        return [self[name] for name in names]

    @property
    def preference_fields(self):
        return self.field_group(self.PREFERENCE_FIELDS)

    @property
    def document_fields(self):
        return self.field_group(self.DOCUMENT_FIELDS)

    def clean_home_airport(self):
        return self.cleaned_data["home_airport"].strip().upper()

    def clean_passport_country(self):
        return self.cleaned_data["passport_country"].strip().upper()


class RewardsMembershipForm(forms.ModelForm):
    class Meta:
        model = RewardsMembership
        fields = ("kind", "program", "member_number", "tier", "expires", "notes")
        widgets = {
            "expires": ISO_DATE_INPUT,
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


RewardsMembershipFormSet = inlineformset_factory(
    Traveler,
    RewardsMembership,
    form=RewardsMembershipForm,
    extra=1,
    can_delete=True,
)
