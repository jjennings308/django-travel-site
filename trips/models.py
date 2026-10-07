"""Relational schema for itinerary content.

The general rule: anything you would filter, sort, or join on is a column.
Anything whose *shape* changes from day to day is JSON in ``Section.content``.

Section payload shapes by ``section_type``
-------------------------------------------

``phase``
    A phase header/introduction block.
    ``{"heading": str, "summary": str, "highlights": [str, ...]}``

``logistics_table``
    A two-column table of logistics (times, costs, who-to-ask-for).
    ``{"columns": [str, ...], "rows": [[cell, ...], ...]}``
    ``rows`` is positional and must line up with ``columns``.

``callout``
    A highlighted warning or tip.
    ``{"tone": "info" | "warning" | "critical", "text": str}``

``choose_your_adventure``
    Several interchangeable options the traveler picks between.
    ``{"prompt": str, "options": [{"title": str, "description": str,
    "duration": str, "cost": str}, ...]}``

``free_text``
    Prose, as authored.
    ``{"paragraphs": [str, ...]}``

Every payload is a JSON *object*, never a bare list or string, so new keys can
be added later without a migration. Renderers should tolerate missing keys and
fall back to omitting the block rather than raising.

Trip status and booking tasks
----------------------------

``Trip.status`` is a *label* for how far along planning is
(``starting`` → ``fleshing_out`` → ``confirming`` → ``ready_to_go``). It is not
an access-control mechanism and nothing should be built that treats it as one.

``BookingTask`` holds what is still outstanding. ``Trip.is_ready`` and
``Trip.outstanding_booking_tasks`` read across to it — that relationship is why
``status`` is trustworthy rather than decorative. A task may belong to a trip
alone, or optionally to a day and/or a confirmation; both links are
``SET_NULL`` so tidying up a day or a confirmation never destroys the task.

Per-day rosters
---------------

``Day.travelers`` is blank for the common case where the whole group is
together, so most trips need no per-day data at all. ``Day.roster`` resolves
that to the effective travelers for the day, and ``Day.is_split`` says whether
a day narrows the trip. Only a day that actually splits the trip should name
travelers; ``DayAdminForm`` rejects a roster naming someone who is not on the
trip at all.

Ownership and soft delete
-------------------------

``Trip.created_by`` records who made the trip in the app, and is the basis for
the ``delete`` capability. It is nullable because a trip authored in the admin
has no creator, and blank is meaningful rather than missing: those trips were
curated, so only staff may delete them.

``Trip.deleted_at`` makes deletion reversible. A trip owns its days, sections,
meals, confirmations and contacts, so a hard delete would take all of that
away on one misclick with no way back. ``soft_delete()`` only stamps the field;
``TripQuerySet.live()`` hides those trips from every read path, and
``restore()`` brings them back. The residue is deliberate — an app about
remembering trips should not be the place data goes missing.

Comments
--------

``Comment`` is a ``GenericForeignKey``, not a ``Trip`` foreign key. Discussion
belongs in different places — the trip as a whole, a day that has split, a
booking task whose wording is disputed — and the point of the AI work in V3 is
annotating a *specific* day or task rather than the trip generally. A
``Trip``-only comment would have to be loosened later, which on an existing
table means a data migration; a generic one costs nothing now.

It is flat, with no parent pointer. Threads are the obvious thing to add, and
the reason not to is that every reader of a comment list then needs to know
which nodes are collapsed, which makes the printed PDF — the actual artifact
of this app — meaningfully worse. Start flat and add replies if anyone asks.

Access is not stored on the comment. A comment inherits its parent's trip, and
``Comment.trip`` resolves that by walking the generic target; there is no
"who can see this comment" that could disagree with who can see the thing
being discussed.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from accounts.models import ROLE_RANK, Role, effective_role
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import BooleanField, Case, Q, Value, When
from django.utils import timezone as django_timezone

def validate_timezone_name(value):
    """Reject timezone names the stdlib can't resolve."""
    if not value:
        return
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValidationError(
            "%(value)s is not a valid IANA timezone name.",
            params={"value": value},
            code="invalid_timezone",
        )


def get_timezone(name):
    """Return a ``tzinfo`` for an IANA name, or ``None`` if unusable.

    Returns ``None`` rather than raising so that a legacy row with a blank or
    bad timezone still renders, just without local-time conversion.
    """
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None


def localize(value, name):
    """Return ``value`` as an aware datetime in the named zone.

    Falls back to UTC when the zone is blank or unresolvable, so a bad
    timezone degrades instead of blanking the page. Returns ``None`` for a
    missing or non-datetime ``value`` — a template resolves a missing
    variable to the *string* ``"None"``, so check the type.
    """
    if value is None or not isinstance(value, datetime):
        return None
    zone = get_timezone(name)
    if zone is None:
        zone = django_timezone.UTC
    if django_timezone.is_naive(value):
        value = django_timezone.make_aware(value, django_timezone.UTC)
    return django_timezone.localtime(value, zone)


def format_in_zone(value, name, fmt):
    """Format a stored UTC datetime in the given zone, or ``None``."""
    local = localize(value, name)
    return None if local is None else local.strftime(fmt)


def format_local_time(value, name):
    """Format as ``6:05 PM MST``.

    Uses ``%-I`` where the platform supports it (glibc strips the leading
    zero) and falls back to trimming it manually, so the output is stable
    across platforms rather than showing ``06:05 PM`` on Windows.
    """
    local = localize(value, name)
    if local is None:
        return None
    hour = local.strftime("%I").lstrip("0") or "0"
    return f"{hour}:{local.strftime('%M %p')} {local.strftime('%Z')}".strip()


def format_local_date(value, name):
    """Format as ``Thu, Jan 15`` — the local calendar date."""
    local = localize(value, name)
    if local is None:
        return None
    return f"{local.strftime('%a, %b')} {local.day}"


class TripQuerySet(models.QuerySet):
    def live(self):
        """Exclude soft-deleted trips.

        Deleting a trip is reversible, so "deleted" means hidden rather than
        gone. Every read path goes through here, which is what keeps a deleted
        trip out of the list, the detail page and a direct link in one place
        instead of relying on each caller to remember.
        """
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        """Soft-deleted trips. Recovery path only; see ``restore``."""
        return self.filter(deleted_at__isnull=False)

    def visible_to(self, user):
        """Trips ``user`` may read.

        Staff and superusers see everything that is not soft-deleted, which is
        what makes them useful for support without a grant on every trip. An
        inactive account sees nothing at all, so deactivating someone takes
        effect immediately rather than at their next login.

        Otherwise a trip qualifies on *both* counts: there is a grant, and the
        user holds at least ``Viewer`` globally. Requiring both is what stops a
        grant from stranding someone in a half state where a trip shows up in
        their list but nothing on it will open.

        Soft-deleted trips are excluded for everyone, staff included. Recovery
        goes through ``Trip.objects.deleted()`` in the admin, so there is one
        way back in rather than a second reading of every view.
        """
        live = self.live()
        if user is None or not user.is_authenticated or not user.is_active:
            return live.none()
        if user.is_staff or user.is_superuser:
            return live
        # Both conditions share one join on purpose. Split across two filter()
        # calls they could pair a grant to one user with a role held by a
        # different one, which would hand out access that neither fact supports.
        return live.filter(
            grants__user=user,
            grants__user__roles__role__isnull=False,
        ).distinct()

    def public(self, token):
        """The trip behind a public token, or an empty queryset.

        Deliberately **not** `visible_to`, and deliberately *not* the pk: the
        public view is unauthenticated, so the only thing that grants access is
        possession of an unguessable token. A blank or unknown token finds
        nothing, which is what makes a trip with no token simply have no public
        page rather than a public page showing nothing.

        Soft-deleted trips are excluded here too. A token outliving the trip
        would otherwise keep publishing a trip somebody deliberately removed —
        including to whoever was still holding the link.
        """
        if not token:
            return self.none()
        return self.live().filter(public_token=token)


class Traveler(models.Model):
    """A person who can appear on one or more trips.

    The roster and the accounts are one-way joined: **every account is a
    traveler, but most travelers have no account.** ``user`` is the link, and
    it is nullable because a person named on a trip's roster is not thereby
    somebody who signs in. ``on_delete=SET_NULL`` means deleting an account
    never takes the traveler's trips, notes or roster memberships with it —
    the row outlives the login.

    The link is maintained by ``trips.signals``: creating an account
    links (or creates) the matching traveler by exact name, and creating a
    traveler links it back if a matching account already exists. Name matches
    are only trusted when they are unambiguous; ``dedupe_travelers`` merges
    the same-person-different-name rows that make them ambiguous.
    """

    name = models.CharField(max_length=120)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="traveler",
        help_text="The account this person signs in with, if any.",
    )
    home_airport = models.CharField(
        max_length=8,
        blank=True,
        help_text="IATA code, e.g. BOS",
    )
    dietary_notes = models.TextField(blank=True)
    mobility_notes = models.TextField(blank=True)
    passport_country = models.CharField(
        max_length=2,
        blank=True,
        help_text="ISO 3166-1 alpha-2, e.g. US",
    )

    # -- preferences: shown to the person and staff, never on a trip page ----
    class Seat(models.TextChoices):
        AISLE = "aisle", "Aisle"
        WINDOW = "window", "Window"

    class Cabin(models.TextChoices):
        ECONOMY = "economy", "Economy"
        PREMIUM_ECONOMY = "premium_economy", "Premium economy"
        BUSINESS = "business", "Business"
        FIRST = "first", "First"

    class Bed(models.TextChoices):
        KING = "king", "King"
        QUEEN = "queen", "Queen"
        TWO_BEDS = "two_beds", "Two beds"

    class MealPreference(models.TextChoices):
        """The airline special-meal requests, not a diet description.

        Free-form detail ("no shellfish, mild nut allergy") stays in
        ``dietary_notes``; this is the box a booking form actually has.
        """

        VEGETARIAN = "vegetarian", "Vegetarian"
        VEGAN = "vegan", "Vegan"
        KOSHER = "kosher", "Kosher"
        HALAL = "halal", "Halal"
        GLUTEN_FREE = "gluten_free", "Gluten-free"
        DIABETIC = "diabetic", "Diabetic"
        CHILD = "child", "Child"

    seat_preference = models.CharField(
        max_length=10, choices=Seat.choices, blank=True
    )
    cabin_preference = models.CharField(
        max_length=20, choices=Cabin.choices, blank=True
    )
    bed_preference = models.CharField(max_length=10, choices=Bed.choices, blank=True)
    meal_preference = models.CharField(
        max_length=20,
        choices=MealPreference.choices,
        blank=True,
        help_text="The airline special-meal request. Details go in dietary notes.",
    )

    # -- identity documents: private to the person and staff -----------------
    known_traveler_number = models.CharField(
        max_length=25,
        blank=True,
        help_text="TSA PreCheck / Global Entry / NEXUS number.",
    )
    redress_number = models.CharField(max_length=13, blank=True)
    passport_number = models.CharField(max_length=20, blank=True)
    passport_expires = models.DateField(
        null=True,
        blank=True,
        help_text="Many countries require six months left on arrival.",
    )

    #: Values only the person themselves and staff may see. Rewards membership
    #: numbers are private too, as a whole model (see ``RewardsMembership``).
    #: Stored in plaintext, like confirmation numbers — see CLAUDE.md.
    SENSITIVE_FIELDS = (
        "known_traveler_number",
        "redress_number",
        "passport_number",
        "passport_expires",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def is_private_to(self, user):
        """Whether ``user`` may see this traveler's private profile data.

        The one rule: the person whose account is linked, or staff. Not
        co-travelers and not trip editors — being on a trip, or able to edit
        it, says nothing about being allowed someone's passport number. An
        inactive account sees nothing, matching ``Trip.capabilities_for``.
        """
        if user is None or not user.is_authenticated or not user.is_active:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return self.user_id is not None and self.user_id == user.pk


class RewardsMembership(models.Model):
    """One loyalty program a traveler belongs to.

    A model rather than fields on ``Traveler`` because a person has several —
    an airline, a hotel chain, a rail card — and each has its own number, tier
    and expiry. ``CASCADE``: a membership means nothing without its person.

    The member number is private (see ``Traveler.is_private_to``), so
    ``__str__`` never includes it: it is what the admin writes into
    ``LogEntry.object_repr`` and what a formset row shows as its summary.
    """

    class Kind(models.TextChoices):
        AIRLINE = "airline", "Airline"
        HOTEL = "hotel", "Hotel"
        RAIL = "rail", "Rail"
        CAR_RENTAL = "car_rental", "Car rental"
        CREDIT_CARD = "credit_card", "Credit card"
        OTHER = "other", "Other"

    traveler = models.ForeignKey(
        Traveler, on_delete=models.CASCADE, related_name="memberships"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.AIRLINE)
    program = models.CharField(max_length=120, help_text="e.g. Delta SkyMiles")
    member_number = models.CharField(max_length=40)
    tier = models.CharField(max_length=60, blank=True, help_text="e.g. Gold")
    expires = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["kind", "program"]
        constraints = [
            models.UniqueConstraint(
                fields=["traveler", "program"],
                name="unique_membership_per_program",
                violation_error_message="This traveler already has that program.",
            )
        ]

    def __str__(self):
        return f"{self.program} ({self.tier})" if self.tier else self.program

    @property
    def masked_number(self):
        """The last four characters, for anywhere a summary needs a hint."""
        tail = self.member_number[-4:]
        return f"••••{tail}" if tail else ""


class Trip(models.Model):
    """One planned trip. The root of every other model in this app."""

    class Budget(models.TextChoices):
        BUDGET = "budget", "Budget"
        MODERATE = "moderate", "Moderate"
        PREMIUM = "premium", "Premium"
        LUXURY = "luxury", "Luxury"

    class Structure(models.TextChoices):
        GUIDED = "guided", "Guided"
        SEMI_GUIDED = "semi_guided", "Semi-guided"
        SELF_DIRECTED = "self_directed", "Self-directed"

    class Status(models.TextChoices):
        STARTING = "starting", "Starting"
        FLESHING_OUT = "fleshing_out", "Fleshing out"
        CONFIRMING = "confirming", "Confirming"
        READY_TO_GO = "ready_to_go", "Ready to go"

    name = models.CharField(max_length=200)
    destination = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    travelers = models.ManyToManyField(
        Traveler,
        related_name="trips",
        blank=True,
    )
    budget = models.CharField(
        max_length=16,
        choices=Budget.choices,
        blank=True,
    )
    structure = models.CharField(
        max_length=16,
        choices=Structure.choices,
        blank=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.STARTING,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_trips",
        editable=False,
        help_text="Set when the trip is created in the app. Left blank for trips authored in the admin.",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
        db_index=True,
        help_text="Set when the trip is deleted. A deleted trip is hidden everywhere but is never removed, so it can be restored.",
    )
    public_token = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
        db_index=True,
        unique=True,
        help_text="Unguessable key for the public, non-detailed view of this trip. Blank means no public page exists — clearing it revokes the link without touching the trip.",
    )

    objects = TripQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date", "name"]
        indexes = [models.Index(fields=["start_date"])]

    def __str__(self):
        return self.name

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def soft_delete(self):
        """Hide this trip. Nothing is removed, so this is reversible.

        Deliberately not a ``delete()``: a trip owns its days, sections, meals,
        confirmations and contacts, and a hard delete would take all of that
        with it on a single misclick with no way back. The one case where a
        true delete is wanted is a trip that was created in error, and that is
        rare enough to be worth doing deliberately in the admin.
        """
        if self.deleted_at is None:
            self.deleted_at = django_timezone.now()
            self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self):
        """Undo ``soft_delete``."""
        if self.deleted_at is not None:
            self.deleted_at = None
            self.save(update_fields=["deleted_at", "updated_at"])

    @property
    def nights(self):
        return max((self.end_date - self.start_date).days, 0)

    # -- the public view ----------------------------------------------------
    #
    # The public page is a *different shape* of the same trip, not the same page
    # with fields left out. See ``trips/public.py`` for the allowlist and
    # ``templates/public_trip.html`` for what renders it.

    @property
    def public_title(self):
        """A name safe to show anyone: destination and dates, never travellers.

        ``Trip.name`` embeds the travellers — "James & Regan — Taos" — so it
        cannot head a public page even though it is the obvious choice. Derived
        rather than stored, because a second title is a second thing to forget to
        update, and a stale one would be published rather than merely wrong.

        Falls back through destination, then the date range, then a generic
        label: a trip with neither destination nor dates still needs a heading
        that is not an empty element.
        """
        destination = (self.destination or "").strip()
        if destination:
            return f"{destination} · {self.public_dates}"
        return self.public_dates

    @property
    def public_dates(self):
        """The date range, or the single date for a one-day trip.

        Built from ``strftime`` rather than ``date_format`` because these are
        headings, not localised prose, and the rest of this module formats dates
        the same way (see ``format_local_date``). ``%-d`` is glibc's
        "no zero padding", which this project's platforms all are.
        """
        if self.start_date == self.end_date:
            return self.start_date.strftime("%B %-d, %Y")
        return (
            f"{self.start_date.strftime('%B %-d')} – "
            f"{self.end_date.strftime('%-d, %Y')}"
        )

    def enable_public(self):
        """Mint a public token, and return it.

        Idempotent: an existing token is kept rather than rotated, so opening
        this twice does not quietly break a link somebody has already shared.
        Rotating is a deliberate ``rotate_public_token`` call.
        """
        if self.pk is not None and self.public_token is not None:
            return self.public_token
        self.public_token = uuid.uuid4()
        self.save(update_fields=["public_token", "updated_at"])
        return self.public_token

    def rotate_public_token(self):
        """Replace the token, invalidating every link already shared."""
        self.public_token = uuid.uuid4()
        self.save(update_fields=["public_token", "updated_at"])
        return self.public_token

    def revoke_public(self):
        """Remove the public page. The trip itself is untouched.

        Clearing the field rather than deleting a row: revoking is a decision
        about sharing, not about the trip, and it must not be able to take
        anything else with it.
        """
        if self.public_token is not None:
            self.public_token = None
            self.save(update_fields=["public_token", "updated_at"])

    @property
    def is_ready(self):
        return self.status == self.Status.READY_TO_GO

    @property
    def outstanding_booking_tasks(self):
        """Count of booking tasks not yet ticked off.

        Prefers the ``outstanding_task_count`` annotation that TripAdmin adds,
        so the changelist does not fire a query per row. Falls back to a count
        on an unsaved instance to something harmless rather than an error.
        """
        annotated = getattr(self, "outstanding_task_count", None)
        if annotated is not None:
            return annotated
        if self.pk is None:
            return 0
        return self.booking_tasks.filter(done=False).count()

    # -- access ------------------------------------------------------------
    #
    # ``Trip.status`` is not consulted anywhere below, on purpose. It is a
    # planning label, and gating reads on it would mean a trip in progress
    # became unreadable to the very people putting it together.

    def capabilities_for(self, user):
        """Which actions ``user`` may take on this trip, as a set of strings.

        The single place the rule lives; ``can`` is the boolean form. Actions
        are ``view``, ``comment``, ``edit``, ``delete``, ``restore`` and
        ``manage``.

        Read access needs a grant *and* at least Viewer globally. ``comment`` and
        ``edit`` additionally need the matching role. ``delete`` needs edit
        class access *and* ownership — being the ``created_by`` of the trip —
        so an editor who was handed someone else's trip cannot remove it.
        ``restore`` and ``manage`` — changing who can reach this trip — stay
        staff-only: a deleted trip is invisible to everyone, so there is no
        self-service path back, and no user can hand out access they do not
        themselves have.

        A trip authored in the admin has no ``created_by``, so nobody but staff
        can delete it. That is the right default: those trips were curated, and
        the person who curated them is staff.
        """
        if user is None or not user.is_authenticated or not user.is_active:
            return set()
        if user.is_staff or user.is_superuser:
            return {"view", "comment", "edit", "delete", "restore", "manage"}

        allowed = set()
        if not self.grants.filter(user=user).exists():
            return allowed

        held = effective_role(user)
        if held is None:
            return allowed
        allowed.add("view")
        if ROLE_RANK[held] <= ROLE_RANK[Role.COMMENTOR]:
            allowed.add("comment")
        if ROLE_RANK[held] <= ROLE_RANK[Role.EDITOR]:
            allowed.add("edit")
            if self.created_by_id == user.pk:
                allowed.add("delete")
        return allowed

    def can(self, user, action):
        """Whether ``user`` may perform ``action`` on this trip."""
        return action in self.capabilities_for(user)

    def visible_to(self, user):
        return "view" in self.capabilities_for(user)


class TransportLeg(models.Model):
    """One hop between two places: a flight, a train, a drive, a walk.

    This started life as ``Flight`` and was renamed when the Europe draft
    turned out to be train-heavy. Keeping transport in its own model — rather
    than as a ``Section`` JSON payload — is what makes a whole-model redaction
    possible later for the public view, and what lets a leg be rendered
    generically instead of per-day.

    ``mode`` is the discriminator. ``operator`` and ``service_number`` are
    deliberately mode-neutral names — an airline and a flight number for a
    plane, a rail company and a service number for a train, a hire company for
    a rental car. They were ``airline`` / ``flight_number`` until migration
    ``0011``, which renamed the columns and kept the rows, so a train leg no
    longer has two air-specific columns it simply leaves blank. Both stay
    ``blank=True`` and neither is part of what identifies a leg: a leg is its
    origin, destination and times.

    Times are stored in UTC (``USE_TZ`` is on) and converted to the local
    time of each endpoint for display. ``origin_timezone`` and
    ``destination_timezone`` are IANA names — ``America/Denver``, not ``MST`` —
    so that daylight saving is handled automatically. Leave either blank and
    that endpoint simply renders in UTC.
    """

    class Mode(models.TextChoices):
        """How you get from origin to destination."""

        PLANE = "plane", "Flight"
        TRAIN = "train", "Train"
        POV = "pov", "Private vehicle"
        RENTAL_CAR = "rental_car", "Rental car"
        WALKING = "walking", "Walking"
        OTHER = "other", "Other"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="transport")
    # Default rather than required: every row that exists today is a flight, so
    # existing data stays correct without a data migration.
    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.PLANE)
    operator = models.CharField(
        max_length=120,
        blank=True,
        help_text="Airline, rail company, or hire company — whatever carries you",
    )
    service_number = models.CharField(
        max_length=20,
        blank=True,
        help_text="Flight number, train service number, or booking reference",
    )
    confirmation_number = models.CharField(max_length=40, blank=True)
    # IATA codes for a plane, but a train leg has stations and a drive has
    # towns, so this is sized for whatever the mode needs rather than 3 chars.
    origin = models.CharField(
        max_length=120, blank=True, help_text="Airport code, station, or town"
    )
    destination = models.CharField(
        max_length=120, blank=True, help_text="Airport code, station, or town"
    )
    origin_timezone = models.CharField(
        max_length=64,
        blank=True,
        validators=[validate_timezone_name],
        help_text="IANA name for the origin, e.g. America/New_York",
    )
    destination_timezone = models.CharField(
        max_length=64,
        blank=True,
        validators=[validate_timezone_name],
        help_text="IANA name for the destination, e.g. America/Denver",
    )
    departure_at = models.DateTimeField()
    arrival_at = models.DateTimeField()
    cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    currency = models.CharField(max_length=3, default="USD")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["trip", "departure_at"]
        verbose_name_plural = "transport legs"

    def __str__(self):
        number = f" {self.service_number}" if self.service_number else ""
        return f"{self.origin} to {self.destination}{number}".strip()

    def _local(self, value, zone_name):
        return localize(value, zone_name)

    @property
    def departure_local(self):
        """Departure as an aware datetime in the origin's local time."""
        return self._local(self.departure_at, self.origin_timezone)

    @property
    def arrival_local(self):
        """Arrival as an aware datetime in the destination's local time."""
        return self._local(self.arrival_at, self.destination_timezone)

    @property
    def departure_local_str(self):
        """Departure time only, e.g. ``6:00 PM EST``."""
        return format_local_time(self.departure_at, self.origin_timezone)

    @property
    def arrival_local_str(self):
        """Arrival time only, e.g. ``4:30 PM MST``."""
        return format_local_time(self.arrival_at, self.destination_timezone)

    @property
    def departure_local_date(self):
        """Departure's local *date*, e.g. ``Thu, Jan 15``.

        Separate from the time because a leg can depart on one local
        calendar day and arrive on the next.
        """
        return format_local_date(self.departure_at, self.origin_timezone)

    @property
    def arrival_local_date(self):
        """Arrival's local *date*, e.g. ``Thu, Jan 15``."""
        return format_local_date(self.arrival_at, self.destination_timezone)

    @property
    def departs_on_a_different_day(self):
        """True when arrival lands on a later local day than departure."""
        departure = self.departure_local
        arrival = self.arrival_local
        if departure is None or arrival is None:
            return False
        return departure.date() != arrival.date()

    @property
    def duration(self):
        """Elapsed time in ``timedelta``, or ``None`` if arrival is missing."""
        if self.departure_at is None or self.arrival_at is None:
            return None
        return self.arrival_at - self.departure_at

    @property
    def duration_str(self):
        """A short human duration, e.g. ``7h 15m`` or ``1d 3h``.

        The raw ``duration`` is a ``timedelta``, which Django renders as
        ``7:15:00`` — fine for a machine, useless on an itinerary card.
        """
        delta = self.duration
        if delta is None:
            return ""
        total_minutes = int(delta.total_seconds() // 60)
        days, remainder = divmod(total_minutes, 24 * 60)
        hours, minutes = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        return " ".join(parts)


class Lodging(models.Model):
    """A place to stay for part or all of a trip."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="lodging")
    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    confirmation_number = models.CharField(max_length=40, blank=True)
    check_in = models.DateField()
    check_out = models.DateField()
    nightly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    currency = models.CharField(max_length=3, default="USD")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["check_in"]
        verbose_name_plural = "lodging"

    def __str__(self):
        return self.name

    @property
    def nights(self):
        return max((self.check_out - self.check_in).days, 0)


class Day(models.Model):
    """One calendar day of a trip.

    A day may narrow who is on it. ``travelers`` blank means the whole trip is
    together, which is the common case and needs no per-day data; naming
    travelers means only those are on that day. This is what lets a trip record
    the two people who fly home early, or the group of four who take the
    optional day trip while two stay in town.
    """

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="days")
    day_number = models.PositiveSmallIntegerField()
    date = models.DateField()
    theme = models.CharField(
        max_length=200,
        blank=True,
        help_text="One-line summary of the day",
    )
    meals_included = models.BooleanField(
        default=False,
        help_text="Meals are already covered by the trip price",
    )
    travelers = models.ManyToManyField(
        Traveler,
        related_name="days",
        blank=True,
        help_text=(
            "Leave blank if the whole group is together. Set it only when this "
            "day splits the trip up."
        ),
    )

    class Meta:
        ordering = ["trip", "day_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["trip", "day_number"],
                name="unique_day_number_per_trip",
            )
        ]

    def __str__(self):
        return f"Day {self.day_number}: {self.theme or self.date}"

    @property
    def is_split(self):
        """True when this day names its own roster instead of using the whole trip."""
        if self.pk is None:
            return False
        # `.exists()` always hits the database, even on a prefetched relation,
        # which would make a day changelist one query per row. Read the
        # prefetch cache directly when it is there.
        cache = getattr(self, "_prefetched_objects_cache", None)
        if cache is not None and "travelers" in cache:
            return bool(cache["travelers"])
        return self.travelers.exists()

    @property
    def roster(self):
        """The travelers actually on this day: its own roster, else the whole trip.

        Returns a queryset, so it composes in templates and views. Iterating
        days should prefetch ``travelers`` and ``trip__travelers``; without
        that this costs two queries per day.
        """
        if self.is_split:
            return self.travelers.all()
        return self.trip.travelers.all()

    @property
    def roster_summary(self):
        """Short human label: 'Whole trip' or 'Ada, Bo'."""
        if not self.is_split:
            return "Whole trip"
        return ", ".join(traveler.name for traveler in self.travelers.all())


class Section(models.Model):
    """An ordered content block within a day.

    See the module docstring for the expected ``content`` shape per
    ``section_type``. Structured presentation attributes stay relational so
    they remain queryable and sortable; only the payload is JSON.
    """

    class Type(models.TextChoices):
        PHASE = "phase", "Phase"
        LOGISTICS_TABLE = "logistics_table", "Logistics table"
        CALLOUT = "callout", "Callout"
        CHOOSE_YOUR_ADVENTURE = "choose_your_adventure", "Choose your adventure"
        FREE_TEXT = "free_text", "Free text"

    day = models.ForeignKey(Day, on_delete=models.CASCADE, related_name="sections")
    section_type = models.CharField(max_length=32, choices=Type.choices)
    title = models.CharField(max_length=200, blank=True)
    icon = models.CharField(max_length=32, blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    content = models.JSONField(default=dict)

    class Meta:
        ordering = ["day", "order", "id"]
        indexes = [models.Index(fields=["day", "order"])]

    def __str__(self):
        return self.title or self.get_section_type_display()

    def content_summary(self):
        """A short, type-appropriate label for the section list.

        One line, so the day page can show what each block actually is without
        rendering it. Deliberately not the same text the detail page shows: this
        is an identifier for a list row, not a preview of the content.

        Every branch tolerates a missing or wrong-typed key. `content` is a raw
        JSON blob written by importers, so a section may carry a shape this app
        does not know — and a summary line that raised would take down the whole
        day page rather than one cell of it.
        """
        content = self.content if isinstance(self.content, dict) else {}

        def text(*keys):
            """First of `keys` that is a non-empty string, trimmed."""
            for key in keys:
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return " ".join(value.split())
            return ""

        if self.section_type == self.Type.PHASE:
            return text("heading")[:90]
        if self.section_type == self.Type.CALLOUT:
            return text("text")[:90]
        if self.section_type == self.Type.FREE_TEXT:
            paragraphs = content.get("paragraphs")
            count = len(paragraphs) if isinstance(paragraphs, list) else 0
            return f"{count} paragraph{'' if count == 1 else 's'}"
        if self.section_type == self.Type.LOGISTICS_TABLE:
            rows = content.get("rows")
            count = len(rows) if isinstance(rows, list) else 0
            return f"{count} row{'' if count == 1 else 's'}"
        if self.section_type == self.Type.CHOOSE_YOUR_ADVENTURE:
            options = content.get("options")
            count = len(options) if isinstance(options, list) else 0
            return f"{count} option{'' if count == 1 else 's'}"
        return ""


class Meal(models.Model):
    """One restaurant or food stop on a given day."""

    class MealType(models.TextChoices):
        BREAKFAST = "breakfast", "Breakfast"
        LUNCH = "lunch", "Lunch"
        DINNER = "dinner", "Dinner"
        SNACK = "snack", "Snack"
        DRINKS = "drinks", "Drinks"

    class PriceRange(models.TextChoices):
        BUDGET = "$", "$"
        MODERATE = "$$", "$$"
        UPSCALE = "$$$", "$$$"
        FINE_DINING = "$$$$", "$$$$"

    day = models.ForeignKey(Day, on_delete=models.CASCADE, related_name="meals")
    name = models.CharField(max_length=200)
    meal_type = models.CharField(max_length=16, choices=MealType.choices)
    cuisine = models.CharField(max_length=100, blank=True)
    price_range = models.CharField(
        max_length=8,
        choices=PriceRange.choices,
        blank=True,
    )
    why_recommended = models.TextField(blank=True)
    reservation_notes = models.TextField(
        blank=True,
        help_text="How to book, when to book, booking reference",
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["day", "order", "id"]

    def __str__(self):
        return f"{self.name} ({self.get_meal_type_display()})"


class Confirmation(models.Model):
    """A booking reference, collected so it is all in one place."""

    trip = models.ForeignKey(
        Trip,
        on_delete=models.CASCADE,
        related_name="confirmations",
    )
    label = models.CharField(
        max_length=200,
        help_text="What this is, e.g. 'Hotel' or 'Airport transfer'",
    )
    confirmation_number = models.CharField(max_length=60)
    provider = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["label"]
        verbose_name_plural = "confirmations"

    def __str__(self):
        return f"{self.label}: {self.confirmation_number}"


class Contact(models.Model):
    """A person or business the traveler may need to reach."""

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class BookingTask(models.Model):
    """Something still to book, decide or confirm for a trip.

    Trips are documented at wildly different stages. A finished trip has
    everything confirmed and no tasks; a trip being planned is mostly tasks —
    "book the Gulmarg flights", "decide between these two hotels". Modelling
    that explicitly is what lets ``Trip.status`` mean something, because the
    outstanding list is the evidence for a trip not being ready yet.

    A task is deliberately allowed to be attached to nothing but a trip.
    Travel documents use booking tasks as a catch-all bucket, and early on
    there is nothing to hang them against. ``day`` and ``confirmation`` are
    therefore both optional, and both ``SET_NULL`` — deleting a day, or a
    confirmation after the fact, should drop the link rather than delete the
    task and the reasoning behind it.
    """

    class Priority(models.IntegerChoices):
        CRITICAL = 1, "Critical"
        HIGH = 2, "High"
        MEDIUM = 3, "Medium"
        LOW = 4, "Low"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="booking_tasks")
    day = models.ForeignKey(
        Day,
        on_delete=models.SET_NULL,
        related_name="booking_tasks",
        null=True,
        blank=True,
    )
    confirmation = models.ForeignKey(
        Confirmation,
        on_delete=models.SET_NULL,
        related_name="booking_tasks",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=200)
    priority = models.IntegerField(choices=Priority.choices, default=Priority.MEDIUM)
    due = models.DateField(
        null=True,
        blank=True,
        help_text="Hard deadline, if there is one",
    )
    due_note = models.CharField(
        max_length=120,
        blank=True,
        help_text="Soft deadline or trigger, e.g. 'before Sept 24'",
    )
    notes = models.TextField(blank=True)
    done = models.BooleanField(default=False)
    order = models.PositiveIntegerField(
        default=0,
        help_text="Lower sorts first within a priority; leave at 0 unless you care",
    )

    class Meta:
        ordering = ["done", "priority", "order", "id"]
        verbose_name = "booking task"
        verbose_name_plural = "booking tasks"
        indexes = [models.Index(fields=["trip", "done"])]

    def __str__(self):
        return self.title


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------

# Content types a comment may be attached to, and the path from that object to
# its trip. The path is what makes a comment's access a *derived* fact: there is
# no way to store a comment whose reader cannot see the thing it is about.
#
# Kept as an explicit mapping rather than a getattr walk. A generic walk would
# quietly support any model with a `trip` attribute, which means a comment could
# be attached to something whose access rules nobody worked out; adding a type
# here should be a decision, not an accident.
COMMENT_TRIP_PATHS = {
    Trip: (),
    Day: ("trip",),
    Section: ("day", "trip"),
    BookingTask: ("trip",),
}

# URL name -> model, for the target part of a comment URL. The single list: the
# view's lookup, the reverse-URL helper and the grouping in the view all read
# from this rather than each holding their own copy. They have to agree, and
# they did not once — the grouping keyed off ``content_type.model`` (``bookingtask``)
# while the template asked for the URL name (``task``), so booking-task threads
# rendered nowhere and the two names looked interchangeable.
COMMENT_TARGET_KINDS = {
    "trip": Trip,
    "day": Day,
    "section": Section,
    "task": BookingTask,
}


def comment_kind(obj):
    """The URL name for ``obj``'s type, or ``None`` if it is not commentable.

    The inverse of looking a name up in ``COMMENT_TARGET_KINDS``, and lives next
    to it so the mapping is only ever extended in one place.
    """
    for kind, model in COMMENT_TARGET_KINDS.items():
        if type(obj) is model:
            return kind
    return None


def comment_trip(obj):
    """The trip ``obj`` belongs to, or ``None`` if it is not commentable.

    ``None`` means "not a supported target", which callers must treat as a
    refusal rather than as "a trip nobody can see" — the two are different and
    only one of them should be a 404.

    ``Trip`` maps to an empty path, not to ``("trip",)``: a trip has no
    ``trip`` attribute, so asking for one would return ``None`` and make every
    comment on a trip itself unreachable.
    """
    if obj is None:
        return None
    path = COMMENT_TRIP_PATHS.get(type(obj))
    if path is None:
        return None
    for attribute in path:
        obj = getattr(obj, attribute, None)
        if obj is None:
            return None
    return obj


class CommentQuerySet(models.QuerySet):
    def for_target(self, obj):
        """Comments on one object, oldest first."""
        if obj is None:
            return self.none()
        return self.filter(
            content_type=ContentType.objects.get_for_model(obj),
            object_id=obj.pk,
        )

    def annotate_editable(self, user):
        """Add ``can_edit`` to each row for template use.

        ``Comment.can_edit`` is a method, and a template cannot call it with an
        argument, so rendering a thread would mean reaching for ``request.user``
        in the view and looping. Annotating keeps the decision in one place —
        the same rule ``can_edit`` uses — without the loop.

        Inactive accounts get nothing, matching the model method rather than
        being trusted with whatever role rows they still have.
        """
        if user is None or not user.is_authenticated or not user.is_active:
            return self.annotate(can_edit=Value(False, output_field=BooleanField()))
        # Staff can edit anything, which is an unconditional True rather than a
        # condition — hence `pk__isnull=False` on a field that is always the
        # primary key and never null. `Case` takes `When` objects, not bare `Q`s,
        # so the condition has to be wrapped.
        condition = Q(author_id=user.pk)
        if user.is_staff or user.is_superuser:
            condition = Q(pk__isnull=False)
        return self.annotate(
            can_edit=Case(
                When(condition, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )


class Comment(models.Model):
    """One comment on a trip, a day, a section or a booking task.

    Flat, and attached with a ``GenericForeignKey``; see the module docstring for
    why neither is a foreign key to ``Trip``.

    Commenting is the only capability that does not need the target to be
    *editable*. A viewer with the ``commentor`` role has nothing to add on a
    read-only page, and asking them to become an editor to say "I can't do the
    8am hike" would make the role ladder mean less than it does.

    Deleting a comment is a hard delete, unlike a trip or a day. A comment is
    conversational and nothing else references it, so there is nothing to lose
    by removing it — keeping a tombstone would preserve the fact that someone
    said something, which is a different product than the one being built.
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trip_comments",
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    # `PositiveBigIntegerField`, not `PositiveIntegerField`: every model here
    # defaults to `BigAutoField`, so a 32-bit column would be narrower than the
    # ids it has to hold. Harmless at trip-sized ids and wrong in principle, and
    # the migration is far cheaper to fix before it ships than after.
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    objects = CommentQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["content_type", "object_id", "created_at"])]

    def __str__(self):
        return f"{self.author}: {self.body[:40]}"

    def trip(self):
        """The trip this comment is about, or ``None`` if unattached.

        ``None`` covers a comment whose target has since been deleted: a
        ``GenericForeignKey`` has no cascading delete of its own, so the row
        survives with an ``object_id`` pointing at nothing. Callers must not
        treat that as permission to show it anywhere.
        """
        return comment_trip(self.content_object)

    def can_edit(self, user):
        """Whether ``user`` may edit or delete this comment.

        Own comment, or staff. Not an editor of the trip — being able to change
        the plan does not make someone's remark about it yours to rewrite.
        """
        if user is None or not user.is_authenticated or not user.is_active:
            return False
        if user.is_staff or user.is_superuser:
            return True
        return self.author_id == user.pk

    def save(self, *args, **kwargs):
        if self.body is not None:
            self.body = self.body.strip()
        return super().save(*args, **kwargs)


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------
#
# There are two axes here and they are deliberately different facts:
#
# * ``UserRole`` is a user's app-wide standing — what kind of thing the person
#   is allowed to do. It says nothing about *where*. It lives in
#   ``accounts``, not here; only ``TripGrant`` is a trips concern.
# * ``TripGrant`` says which trips a person can reach. It carries no role,
#   because the role already lives on the user.
#
# Neither is ``Trip.travelers``. "Regan is on the trip" and "Regan can read the
# trip" are unrelated facts: a trip can have six travelers and one reader, and a
# public view needs to drop the names without dropping the trip.
#
# Neither is ``Trip.status`` either. Status records how far planning has got; it
# is a label shown to people who already have access, never a gate. This is why
# ``visible_to`` does not mention it.


def can_create_trip(user):
    """Whether ``user`` may author a new trip.

    App-wide rather than per-trip, because it is about the person rather than
    any one trip. Nothing builds on this yet — all trips are still authored in
    the admin — but it is the check the future create view will use, so it lives
    with the other rules rather than in a view.
    """
    if user is None or not user.is_authenticated or not user.is_active:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return effective_role(user) == Role.CREATOR


class TripGrant(models.Model):
    """Permission for one user to reach one trip.

    This is deliberately role-free. What a user may *do* once they can reach a
    trip is their ``UserRole``; this only answers *which* trips they can see,
    and it exists because a private trip should not be readable by every account
    that exists.

    The grant is one row, not a role, so revoking access is deleting the row and
    leaves nothing half-revoked. ``granted_by`` records who let the person in,
    which is worth keeping on a private trip carrying confirmation numbers.
    """

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="grants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="trip_grants",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["trip", "user"]
        verbose_name = "trip grant"
        verbose_name_plural = "trip grants"
        constraints = [
            models.UniqueConstraint(fields=["trip", "user"], name="unique_trip_grant"),
        ]

    def __str__(self):
        return f"{self.user} → {self.trip}"
