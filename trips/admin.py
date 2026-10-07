import re

from django.contrib import admin, messages
from django.contrib.admin import site
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html

from .forms import DayAdminForm, TransportLegAdminForm
from .models import (
    BookingTask,
    Confirmation,
    Contact,
    Day,
    TransportLeg,
    Lodging,
    Meal,
    RewardsMembership,
    Section,
    Traveler,
    Trip,
    TripGrant,
)

from accounts.admin import UserAdmin as AccountsUserAdmin, UserRoleInline

User = get_user_model()


class TransportLegInline(admin.TabularInline):
    model = TransportLeg
    form = TransportLegAdminForm
    extra = 1
    fields = (
        "mode",
        "origin",
        "destination",
        "departure_local",
        "origin_timezone",
        "arrival_local",
        "destination_timezone",
        "operator",
        "service_number",
        "cost",
        "currency",
    )


class LodgingInline(admin.TabularInline):
    model = Lodging
    extra = 1
    fields = ("name", "check_in", "check_out", "nightly_rate", "currency", "confirmation_number")


class DayInline(admin.TabularInline):
    """Day summary on the Trip page.

    Per-day rosters (``Day.travelers``) are deliberately absent: a
    horizontal-filter multi-select inside a tabular row is unusable, and it is
    only needed on the occasional split day. Set it on the Day page.
    """

    model = Day
    extra = 0
    fields = ("day_number", "date", "theme", "meals_included")
    ordering = ("day_number",)


class ConfirmationInline(admin.TabularInline):
    model = Confirmation
    extra = 1
    fields = ("label", "confirmation_number", "provider")


class ContactInline(admin.TabularInline):
    model = Contact
    extra = 1
    fields = ("name", "role", "phone", "email")


class BookingTaskInline(admin.TabularInline):
    """Compact checklist on the Trip page.

    Deliberately omits ``notes``, ``day``, ``confirmation`` and ``order``: the
    first two are detail, and picking a day from a dropdown of every day on
    every trip is more error-prone than useful. Follow the change link for the
    full record.
    """

    model = BookingTask
    extra = 1
    fields = ("done", "priority", "title", "due", "due_note")
    ordering = ("done", "priority")
    show_change_link = True


class TripGrantInline(admin.TabularInline):
    """Who can reach this trip, edited from the trip it applies to.

    Access is granted here rather than through a separate screen so the person
    doing it has the trip in front of them — this is a private trip carrying
    confirmation numbers, and a bare user list in a changelist is a poor place
    to hand that out.
    """

    model = TripGrant
    extra = 1
    autocomplete_fields = ("user", "granted_by")
    verbose_name = "access grant"
    verbose_name_plural = "access grants"


class DeletedFilter(admin.SimpleListFilter):
    """Default the changelist to live trips, keep deleted ones reachable.

    A soft-deleted trip still owns its days and confirmations, so staff need to
    be able to find one and put it back. But leaving them in the default
    changelist would mean every ordinary list query carries trips nobody is
    working on, so the filter is inverted: no choice means live only, and
    choosing either side narrows from there.
    """

    title = "deleted"
    parameter_name = "deleted"

    def lookups(self, request, model_admin):
        return (
            ("yes", "Deleted"),
            ("no", "Not deleted"),
        )

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(deleted_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(deleted_at__isnull=True)
        return queryset.filter(deleted_at__isnull=True)


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "start_date",
        "end_date",
        "outstanding",
        "reader_count",
        "deleted_marker",
    )
    list_filter = (DeletedFilter, "status", "budget", "structure")
    search_fields = ("name", "destination")
    date_hierarchy = "start_date"
    filter_horizontal = ("travelers",)
    actions = ("restore_trips", "create_public_links", "revoke_public_links")
    # `public_token` is `editable=False` on the model, so the admin form would
    # drop it silently and there would be nowhere to find the link. This renders
    # it instead, and the two actions below are the only ways it changes.
    readonly_fields = ("public_link",)
    inlines = [
        BookingTaskInline,
        DayInline,
        TransportLegInline,
        LodgingInline,
        ConfirmationInline,
        ContactInline,
        TripGrantInline,
    ]

    def get_queryset(self, request):
        # Annotate rather than let the changelist call the property per row,
        # which would mean one COUNT query per trip. The property prefers this
        # annotation when it is present.
        return (
            super()
            .get_queryset(request)
            .annotate(
                outstanding_task_count=Count(
                    "booking_tasks", filter=Q(booking_tasks__done=False)
                ),
                granted_user_count=Count("grants", distinct=True),
            )
        )

    @admin.display(boolean=True, description="deleted", ordering="deleted_at")
    def deleted_marker(self, obj):
        return obj.is_deleted

    @admin.action(description="Restore selected trips (undo a soft delete)")
    def restore_trips(self, request, queryset):
        """Bring soft-deleted trips back.

        Filtering to the deleted ones inside the action rather than trusting
        the changelist: a staff member can reach this from a live selection and
        a no-op is harmless, whereas restoring a live trip is what the action
        name would falsely suggest it did.
        """
        restored = 0
        for trip in queryset.filter(deleted_at__isnull=False):
            trip.restore()
            restored += 1
        if restored:
            self.message_user(
                request, f"Restored {restored} trip(s).", messages.SUCCESS
            )
        else:
            self.message_user(
                request,
                "None of the selected trips were deleted. A deleted trip only "
                "appears in the list under the “Deleted” filter.",
                messages.WARNING,
            )

    @admin.display(description="readers", ordering="granted_user_count")
    def reader_count(self, obj):
        return obj.granted_user_count

    @admin.display(description="public link")
    def public_link(self, obj):
        """The shareable URL, or a note that there isn't one.

        A form field for a token would mean a typed value could replace it, and
        two people sharing a link would end up with two tokens — so minting is an
        action and this is display only.
        """
        if obj.pk is None or not obj.public_token:
            return "Not shared. Select this trip and use “Create public link”."
        url = reverse("public_trip", args=[obj.public_token])
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">{}</a>'
            '<br><span class="help">A summary only: no names, flights or booking '
            "references. Use “Revoke public link” to stop sharing.</span>",
            url,
            url,
        )

    @admin.action(description="Create the public link for selected trips")
    def create_public_links(self, request, queryset):
        """Mint a token per trip, keeping any that already exists.

        Idempotent because a changelist selection often includes a trip that is
        already shared, and rotating it would break a link somebody has.
        """
        created = kept = 0
        for trip in queryset.filter(deleted_at__isnull=True):
            if trip.public_token:
                kept += 1
                continue
            trip.enable_public()
            created += 1
        self.message_user(
            request,
            f"Public link ready for {created} trip(s); {kept} already had one "
            f"and were left alone.",
            messages.SUCCESS,
        )

    @admin.action(description="Revoke the public link for selected trips")
    def revoke_public_links(self, request, queryset):
        """Take the public page down without touching the trip.

        A warning rather than a block, because the trip is untouched and the
        token can be minted again — but a shared link stops working the moment
        this runs, which is worth saying out loud.
        """
        revoked = 0
        for trip in queryset:
            if trip.public_token:
                trip.revoke_public()
                revoked += 1
        if revoked:
            self.message_user(
                request,
                f"Revoked the public link for {revoked} trip(s). Any link "
                f"already shared now returns 404.",
                messages.WARNING,
            )
        else:
            self.message_user(
                request, "None of the selected trips had a public link.",
                messages.WARNING,
            )

    @admin.display(description="outstanding", ordering="outstanding_task_count")
    def outstanding(self, obj):
        return obj.outstanding_booking_tasks

    def _warn_if_outstanding(self, request, obj):
        """Nudge, don't block: a trip can be ready to go with tasks still open.

        Hooked into the ``response_*`` callbacks rather than ``save_model``
        because those run after ``save_related``, so the count includes booking
        tasks submitted by the inline in the very same request. Counting in
        ``save_model`` silently under-reports — it would miss a task added at
        the same moment the trip was marked ready.
        """
        if obj.status != Trip.Status.READY_TO_GO:
            return
        remaining = obj.booking_tasks.filter(done=False).count()
        if remaining:
            messages.warning(
                request,
                f"Marked ready to go with {remaining} outstanding booking "
                f"task{'s' if remaining != 1 else ''}.",
            )

    def response_add(self, request, obj, post_url_continue=None):
        self._warn_if_outstanding(request, obj)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        self._warn_if_outstanding(request, obj)
        return super().response_change(request, obj)


class SectionInline(admin.StackedInline):
    model = Section
    extra = 0
    fields = ("section_type", "title", "icon", "order", "content")
    ordering = ("order",)


class MealInline(admin.TabularInline):
    model = Meal
    extra = 1
    fields = ("name", "meal_type", "cuisine", "price_range", "reservation_notes", "order")


class RosterFilter(admin.SimpleListFilter):
    """Split a day list into the days that narrow the group and the rest.

    The useful question when reviewing a trip is "which days do we split up?",
    which is exactly what a M2M-free list filter cannot answer inline.
    """

    title = "roster"
    parameter_name = "roster"

    def lookups(self, request, model_admin):
        return (
            ("split", "Narrows the group"),
            ("whole", "Whole trip"),
        )

    def queryset(self, request, queryset):
        if self.value() == "split":
            return queryset.filter(travelers__isnull=False).distinct()
        if self.value() == "whole":
            return queryset.filter(travelers__isnull=True)
        return queryset


@admin.register(Day)
class DayAdmin(admin.ModelAdmin):
    form = DayAdminForm
    list_display = (
        "__str__",
        "trip",
        "day_number",
        "date",
        "meals_included",
        "roster_summary",
    )
    list_filter = ("trip", "meals_included", RosterFilter)
    search_fields = ("theme",)
    filter_horizontal = ("travelers",)
    inlines = [SectionInline, MealInline]

    def get_queryset(self, request):
        # roster_summary reads the day roster on every row, so prefetch it and
        # the trip's travelers to keep the changelist a fixed query count.
        return super().get_queryset(request).prefetch_related(
            "travelers", "trip__travelers"
        )


class RewardsMembershipInline(admin.TabularInline):
    model = RewardsMembership
    extra = 0
    fields = ("kind", "program", "member_number", "tier", "expires")


@admin.register(Traveler)
class TravelerAdmin(admin.ModelAdmin):
    """The roster, with the account question on every row.

    ``create_accounts`` is the one place an account is made *for* an existing
    traveler: it attaches to this row, so the trips, notes and roster
    memberships the traveler already has all come along. Accounts made here
    have an unusable password until one is set on the user page, and no role
    or trip access is granted — access stays a separate, deliberate act.
    """

    list_display = ("name", "account", "home_airport", "passport_country", "trip_count")
    search_fields = ("name",)
    autocomplete_fields = ("user",)
    actions = ["create_accounts"]
    inlines = [RewardsMembershipInline]
    fieldsets = (
        (None, {"fields": ("name", "user", "home_airport")}),
        (
            "Preferences",
            {
                "fields": (
                    ("seat_preference", "cabin_preference"),
                    ("bed_preference", "meal_preference"),
                    "dietary_notes",
                    "mobility_notes",
                )
            },
        ),
        (
            "Trusted traveler & passport (private to the person and staff)",
            {
                "fields": (
                    ("known_traveler_number", "redress_number"),
                    ("passport_country", "passport_number", "passport_expires"),
                )
            },
        ),
    )

    @admin.display(description="trips")
    def trip_count(self, obj):
        return obj.trips.count()

    @admin.display(description="account")
    def account(self, obj):
        return obj.user.username if obj.user_id else "no account"

    @admin.action(description="Create an account for selected travelers")
    def create_accounts(self, request, queryset):
        for traveler in queryset:
            username, error = self._make_account(traveler)
            if error:
                self.message_user(request, error, messages.WARNING)
                continue
            self.message_user(
                request,
                f"Created account '{username}' for {traveler.name}. "
                "Set a password on the user page before they can sign in.",
                messages.SUCCESS,
            )

    def _make_account(self, traveler):
        """Create and link one account. Returns ``(username, error)``."""
        if traveler.user_id:
            return None, (
                f"{traveler.name} already has the account "
                f"'{traveler.user.username}'."
            )
        parts = traveler.name.split()
        if not parts or not re.findall(r"[a-z0-9]+", traveler.name.lower()):
            return None, f"{traveler.name!r} has no name to derive an account from."
        full_name = " ".join(parts)
        # The signal links by the account's full name, so a second row spelled
        # differently ("Debbie" vs "Debbie Fowler") would be a trap: either
        # ambiguity is resolved first, or no account is made.
        if (
            Traveler.objects.filter(name__in={traveler.name, full_name}).count()
            > 1
        ):
            return None, (
                f"More than one traveler answers to {full_name!r}; "
                "merge them with dedupe_travelers first."
            )
        user = User.objects.create(
            username=_username_for(traveler.name),
            first_name=parts[0],
            last_name=" ".join(parts[1:]),
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        # The signal has normally linked this row already (full name to name).
        # If it instead built a fresh row because the spellings differed, that
        # row is empty and unattached — proven above to be the only extra — so
        # this row gets the link and no duplicate survives.
        made = Traveler.objects.filter(user=user).first()
        if made is not None and made.pk != traveler.pk:
            made.delete()
        Traveler.objects.filter(pk=traveler.pk, user=None).update(user=user)
        return user.username, None


def _username_for(name):
    """A free username derived from a traveler name: first word, lowercase.

    Collisions fall back to the whole name squashed, then to numbered
    suffixes, so "Debbie Fowler" becomes ``debbie`` and a second "Debbie
    Fowler" becomes ``debbiefowler`` rather than failing the save.
    """
    words = re.findall(r"[a-z0-9]+", name.lower()) or ["user"]
    stems = list(dict.fromkeys([words[0], "".join(words)]))
    for stem in stems:
        if not User.objects.filter(username=stem).exists():
            return stem
    suffix = 2
    while True:
        candidate = f"{stems[0][: 150 - len(str(suffix))]}{suffix}"
        if not User.objects.filter(username=candidate).exists():
            return candidate
        suffix += 1


@admin.register(RewardsMembership)
class RewardsMembershipAdmin(admin.ModelAdmin):
    # Not the member number: the changelist is a list of everybody's programs,
    # and a number in a column is a number on a screen. It is on the change page.
    list_display = ("program", "traveler", "kind", "tier", "expires")
    list_filter = ("kind",)
    search_fields = ("program", "traveler__name")
    autocomplete_fields = ("traveler",)


@admin.register(Confirmation)
class ConfirmationAdmin(admin.ModelAdmin):
    list_display = ("label", "confirmation_number", "provider", "trip")
    list_filter = ("trip",)
    search_fields = ("label", "confirmation_number", "provider")


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "phone", "email", "trip")
    list_filter = ("trip",)
    search_fields = ("name", "role", "email")


@admin.register(BookingTask)
class BookingTaskAdmin(admin.ModelAdmin):
    # `title` leads so it stays the link to the change page; `done` and
    # `priority` are editable inline because ticking tasks off in bulk is the
    # whole point of the list view.
    list_display = ("title", "done", "priority", "trip", "due", "day", "confirmation")
    list_display_links = ("title",)
    list_editable = ("done", "priority")
    list_filter = ("done", "priority", "trip")
    search_fields = ("title", "notes", "due_note")
    autocomplete_fields = ("trip", "day", "confirmation")


@admin.register(TransportLeg)
class TransportLegAdmin(admin.ModelAdmin):
    form = TransportLegAdminForm
    list_display = (
        "__str__",
        "trip",
        "mode",
        "departure_when_local",
        "arrival_when_local",
        "duration_display",
        "cost",
        "currency",
    )
    list_filter = ("trip", "mode")
    date_hierarchy = "departure_at"

    @admin.display(description="departs (local)")
    def departure_when_local(self, obj):
        return self._local_when(obj.departure_local_date, obj.departure_local_str)

    @admin.display(description="arrives (local)")
    def arrival_when_local(self, obj):
        return self._local_when(obj.arrival_local_date, obj.arrival_local_str)

    @staticmethod
    def _local_when(date_str, time_str):
        """Join a local date and time, tolerating an unsaved row."""
        if not date_str or not time_str:
            return ""
        return f"{date_str} {time_str}"

    @admin.display(description="duration")
    def duration_display(self, obj):
        total = obj.duration
        if total is None:
            return ""
        hours, remainder = divmod(int(total.total_seconds()), 3600)
        minutes = remainder // 60
        return f"{hours}h {minutes:02d}m"


@admin.register(Lodging)
class LodgingAdmin(admin.ModelAdmin):
    list_display = ("name", "trip", "check_in", "check_out", "nightly_rate", "currency")
    list_filter = ("trip",)
    date_hierarchy = "check_in"
    search_fields = ("name", "address")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "day", "section_type", "order")
    list_filter = ("section_type",)
    ordering = ("day", "order")


@admin.register(Meal)
class MealAdmin(admin.ModelAdmin):
    list_display = ("name", "meal_type", "cuisine", "price_range", "day")
    list_filter = ("meal_type", "cuisine")
    search_fields = ("name", "cuisine")


@admin.register(TripGrant)
class TripGrantAdmin(admin.ModelAdmin):
    list_display = ("user", "trip", "granted_by", "granted_at")
    list_filter = ("trip",)
    search_fields = ("user__username", "user__email", "trip__name")
    autocomplete_fields = ("user", "trip", "granted_by")


class UserTripGrantInline(admin.TabularInline):
    """Trip access editable from the user: who can read what.

    A separate class from the trip-side :class:`TripGrantInline` because that
    one is parented on ``Trip`` and needs no ``fk_name``, while this one is
    parented on ``User`` and must say which of the two user FKs it fills.
    """

    model = TripGrant
    fk_name = "user"
    extra = 1
    autocomplete_fields = ("trip", "granted_by")
    verbose_name = "trip access"
    verbose_name_plural = "trip access"


# The accounts User admin has no notion of an app role or of which trips someone
# can read, so it is swapped for a subclass that carries both. It is registered
# from here, not from accounts, so accounts never imports trips. Unregistering
# is the supported way to do this; there is no `extend` in Django.
site.unregister(User)


class TripsUserAdmin(AccountsUserAdmin):
    """The accounts user admin plus the two things this app adds to a person.

    Roles and trip access are both reachable from the user page, and both from
    their own changelists, because both questions get asked from both
    directions: "what can this account do" and "who can read this trip".
    """

    inlines = list(AccountsUserAdmin.inlines) + [UserRoleInline, UserTripGrantInline]


site.register(User, TripsUserAdmin)
