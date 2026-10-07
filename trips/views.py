"""Read and editing views.

Every queryset here is built through ``Trip.objects.visible_to`` or ``Trip.can``,
so a view cannot accidentally read a trip the requester has no grant for; there
is no "filter it in the template" step to forget. That is why the read views 404
rather than 403 — a 403 would confirm the trip exists to someone with no grant,
which is itself a leak on a private trip carrying confirmation numbers.

The editing views split the two cases apart deliberately: an *invisible* trip is
still a 404, because the reader must not learn that it exists, but a trip the
user can already read and merely not edit is a 403. At that point existence is
not a secret, and answering "not allowed" is more honest than pretending the
trip is not there.

The one exception is ``public_trip_detail`` at the bottom, which resolves through
``Trip.objects.public`` because it is *meant* to be read without an account. It
publishes a fixed allowlisted shape (``trips/public.py``) rather than this
app's models, so nothing private is reachable from it even by a mistake in a
template.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as django_timezone

from accounts.models import ROLE_RANK, Role, effective_role

from .forms import (
    AddTravelerForm,
    CommentForm,
    DayForm,
    MealFormSet,
    RewardsMembershipFormSet,
    SectionForm,
    TravelerProfileForm,
    TripForm,
    section_payload_form,
    trip_subsection_formsets,
)
from .models import (
    BookingTask,
    Comment,
    Day,
    Meal,
    Section,
    Traveler,
    Trip,
    TripGrant,
    can_create_trip,
    comment_kind,
    comment_trip,
    COMMENT_TARGET_KINDS,
)
from .dashboard import build_dashboard
from .public import public_trip


def _visible_capabilities(user, trips):
    """Attach per-row capabilities to trips the user can already read.

    ``Trip.capabilities_for`` is the single place the rule lives, but it costs
    three queries a call — grant exists, roles exists, roles values_list — and
    this is a list page, so a loop over it would be three queries per trip.

    Every trip passed here came out of ``Trip.objects.visible_to``, so the grant
    is already known to exist and the only remaining question is the role, which
    answers the same for every row. So the rule reduces to: staff get
    everything; otherwise an Editor-or-stronger can edit, and can additionally
    delete the trips they created.

    This is a shortcut, not a second rule. ``TripListCapabilityTests`` in
    test_access.py pins it against ``capabilities_for`` for every role, so the
    two cannot quietly diverge.
    """
    staff = user.is_staff or user.is_superuser
    role = effective_role(user)
    editable = staff or (
        role is not None and ROLE_RANK[role] <= ROLE_RANK[Role.EDITOR]
    )
    for trip in trips:
        # Mirrors capabilities_for: ownership is necessary but not sufficient.
        owns = trip.created_by_id == user.pk
        trip.list_capabilities = {
            "edit": editable,
            "delete": staff or (editable and owns),
        }
    return trips


def _days_with_counts(trip):
    """The trip's days, ordered, with meal/section counts and no per-day queries.

    Two `Count`s over two separate reverse relations need `distinct`: without it
    the joins multiply and a day with 3 meals and 2 sections reports 6 of each.

    Both prefetches are load-bearing for the template rather than incidental —
    `Day.is_split` reads `_prefetched_objects_cache`, and `roster_summary`
    resolves blank to the whole group, so a trip with 30 days would otherwise
    cost 60 queries just to draw this table.
    """
    return (
        trip.days.annotate(
            meals_count=Count("meals", distinct=True),
            sections_count=Count("sections", distinct=True),
        )
        .prefetch_related("travelers", "trip__travelers")
        .order_by("day_number")
    )


def _day_sections(day):
    """The day's sections in display order.

    `order` first, then `pk`, so two sections left at the same order (the
    default) keep the sequence they were entered in instead of sorting
    arbitrarily by something the reader never chose.
    """
    return day.sections.order_by("order", "pk")


@login_required
def trip_list(request):
    """Trips the signed-in user may read.

    A staff member sees every trip, which is why the list doubles as the place
    an admin-supporting user lands. Draft labelling is a display concern only:
    a trip is a draft because its status says so, never because the reader is
    allowed a lesser view of it.

    The outstanding-task count and the day count are annotated rather than
    left to properties, which would fire one COUNT per row. Travelers are
    prefetched for the same reason: the list cards name who is going, and
    without the prefetch that is one query per trip.
    """
    trips = list(
        Trip.objects.visible_to(request.user)
        .prefetch_related("travelers")
        .annotate(
            outstanding_task_count=Count(
                "booking_tasks", filter=Q(booking_tasks__done=False), distinct=True
            ),
            days_count=Count("days", distinct=True),
        )
    )
    _visible_capabilities(request.user, trips)
    return render(
        request,
        "trips/trip_list.html",
        {
            "trips": trips,
            "is_staff_view": request.user.is_staff or request.user.is_superuser,
            "can_create": can_create_trip(request.user),
        },
    )


@login_required
def dashboard(request):
    """Site-wide trip totals, for staff. Mounted under ``/staff/trips/``.

    Gated by ``User.can_access_staff`` (superuser or the
    ``accounts.can_access_staff_dashboard`` permission), like the rest of
    ``/staff/``, and a 403 rather than a 404 for a signed-in reader without it:
    the page's existence is not a secret, and every trip it counts is one staff
    can already see. Anonymous visitors are sent to login like any other page.

    The figures come from ``build_dashboard()``, which reads every live trip
    directly rather than through ``visible_to`` — see that module for why a
    staff dashboard should not be filtered by grants.
    """
    if not request.user.can_access_staff:
        raise PermissionDenied
    return render(request, "trips/staff_dashboard.html", {"stats": build_dashboard()})


def _trip_comments(trip, user):
    """Every comment on ``trip``, grouped by the target it is about.

    Returns ``({(kind, pk): [comments]}, {kind: {pk: [...]}})`` — the first for
    direct lookup by the view, the second for the template, which would
    otherwise have to build tuple keys inside a nested loop.

    One query for all four target kinds rather than one per day or section. The
    trip already holds its days, sections and tasks in prefetched lists, so the
    object ids are known without asking; a single ``content_type``/``object_id``
    filter over their union is one query where a loop would be one per day.

    The grouping key is the *URL* name from ``COMMENT_TARGET_KINDS``, not
    ``content_type.model``. The two differ — the model name for a booking task is
    ``bookingtask`` — and using the wrong one silently produced threads that no
    template ever asked for.

    Comments render on the detail page rather than only on the editing pages
    because those require ``edit``: a ``commentor`` who is not an editor could
    post about a day and then have nowhere to read their own comment back.
    """
    days = list(trip.days.all())
    ids = {
        "trip": [trip.pk],
        "day": [d.pk for d in days],
        # `ordered_sections` is a prefetch `to_attr` on Day, so it is already on
        # the day instances the page is holding rather than a further query.
        "section": [s.pk for d in days for s in d.ordered_sections],
        "task": [t.pk for t in trip.booking_tasks.all()],
    }

    # One `get_for_models` call for all four kinds. `get_for_model` is one query
    # per model, so four kinds would have cost four queries on every trip page
    # render — a fixed tax on the page's query count for no information.
    content_types = ContentType.objects.get_for_models(*COMMENT_TARGET_KINDS.values())
    kind_for_content_type = {
        content_types[model].pk: kind
        for kind, model in COMMENT_TARGET_KINDS.items()
    }

    condition = Q()
    for kind, model in COMMENT_TARGET_KINDS.items():
        if ids.get(kind):
            condition |= Q(
                content_type=content_types[model],
                object_id__in=ids[kind],
            )

    rows = (
        Comment.objects.filter(condition)
        .annotate_editable(user)
        .select_related("author")
    )
    by_target = {}
    for row in rows:
        kind = kind_for_content_type.get(row.content_type_id)
        if kind is None:
            # Only reachable if a comment points at a model this page does not
            # render. Not an error, but it has nowhere to go.
            continue
        by_target.setdefault((kind, row.object_id), []).append(row)

    grouped = {kind: {} for kind in COMMENT_TARGET_KINDS}
    for (kind, object_id), comments in by_target.items():
        grouped[kind][object_id] = comments
    return by_target, grouped


@login_required
def trip_detail(request, pk):
    """One trip, in full, for printing.

    The whole page exists to be printed, so it is assembled for a reader rather
    than an editor: sections in order, meals in order, and the quick-reference
    cards that make confirmation numbers findable without scrolling.

    Everything hangs off one ``visible_to`` lookup so an ungranted trip 404s at
    the first query. The related rows are then prefetched in a fixed number of
    queries — a trip has ~17 days, and without this the page would run a query
    per section, per meal and per day, which is the difference between one
    screen and a hundred.
    """
    trip = get_object_or_404(
        Trip.objects.visible_to(request.user)
        .prefetch_related(
            # Only the *leaf* relations carry to_attr. Putting one on "days" as
            # well silently breaks the chain: the sections get fetched, but
            # Django attaches them to a different set of Day instances than the
            # ones trip.ordered_days holds, so the template's for loop over
            # ordered_sections quietly iterates nothing. Prefetching just the
            # leaves is what makes the template loop work at all.
            Prefetch(
                "days__sections",
                queryset=Section.objects.order_by("order", "id"),
                to_attr="ordered_sections",
            ),
            Prefetch(
                "days__meals",
                queryset=Meal.objects.order_by("order", "id"),
                to_attr="ordered_meals",
            ),
            # The template calls day.is_split and day.roster_summary per day, and
            # is_split only avoids a query when "travelers" is already in the
            # prefetch cache. Without this the page costs one extra query per
            # day — 17 for the Europe trip, purely to ask whether a roster is
            # set.
            "days__travelers",
            "lodging",
            "transport",
            "confirmations",
            "contacts",
            "booking_tasks",
            "travelers",
        )
        .annotate(
            outstanding_task_count=Count(
                "booking_tasks", filter=Q(booking_tasks__done=False), distinct=True
            )
        ),
        pk=pk,
    )
    comments, comments_by_target = _trip_comments(trip, request.user)
    return render(
        request,
        "trips/trip_detail.html",
        {
            "trip": trip,
            "trip_comments": comments.get(("trip", trip.pk), []),
            "comments_by_target": comments_by_target,
            "can_comment": trip.can(request.user, "comment"),
        },
    )


# ---------------------------------------------------------------------------
# Editing
#
# Every view below resolves its trip through the same two steps in the same
# order: find it among the trips this user can *read*, then check the specific
# action. Reversing those would mean asking about an action on a trip whose
# existence the user is not entitled to.
# ---------------------------------------------------------------------------


def _readable_trip(request, pk, action):
    """The trip at ``pk`` if the user may read it and perform ``action``.

    404 first for visibility, then 403 for capability. See the module
    docstring for why the second one is a 403.
    """
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=pk)
    if not trip.can(request.user, action):
        raise PermissionDenied
    return trip


def _add_new_traveler(trip, traveler_form):
    """Attach a newly named traveler to ``trip``, if the form was filled in.

    The traveler form sits on the trip form but is optional, so a blank name is
    the normal case and must stay silent rather than complain.

    Traveler rows are a shared roster, so this reuses an existing row instead of
    creating a second one. Two rows both called "James" would put the same person
    on a trip's roster as two people, and a split day naming one of them would
    then render as a split the rest of the group is not on.
    """
    if not traveler_form.is_valid():
        return
    name = traveler_form.cleaned_data["new_traveler_name"]
    if not name:
        return
    traveler, _ = Traveler.objects.get_or_create(name=name)
    trip.travelers.add(traveler)


@login_required
def trip_create(request):
    """Start a new trip.

    Gated on ``can_create_trip`` rather than on anything about a trip, because
    there is no trip yet to have a grant on.
    """
    if not can_create_trip(request.user):
        raise PermissionDenied

    form = TripForm(request.POST or None)
    traveler_form = AddTravelerForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        trip = form.save(commit=False)
        # Ownership is set here rather than being a form field, so it cannot be
        # set or overwritten by anything a user submits.
        trip.created_by = request.user
        trip.save()
        form.save_m2m()
        _add_new_traveler(trip, traveler_form)

        # A creator who can make a trip but cannot read the result would create
        # something that silently vanishes from their own list. Grant them
        # access to what they just made.
        TripGrant.objects.create(trip=trip, user=request.user, granted_by=request.user)

        messages.success(request, f"Created “{trip.name}”.")
        return redirect("trips:trip_detail", pk=trip.pk)

    return render(
        request,
        "trips/trip_form.html",
        {
            "form": form,
            "traveler_form": traveler_form,
            "is_create": True,
        },
    )


@login_required
def trip_edit(request, pk):
    """Change a trip and its trip-level lists in one submit.

    Lodging, transport, confirmations, contacts and booking tasks are formsets
    on this page rather than separate pages, because that is how they are
    actually entered: a hotel and its confirmation number belong in the same
    save, not two.

    Nothing is written unless *everything* validates. A half-applied edit is
    worse than a rejected one — the error message points at a form the reader
    has already scrolled past, and the trip is left in a state neither the
    person nor the app intended.
    """
    trip = _readable_trip(request, pk, "edit")
    form = TripForm(request.POST or None, instance=trip)
    traveler_form = AddTravelerForm(request.POST or None)
    formsets = trip_subsection_formsets(trip, request.POST or None)

    if request.method == "POST":
        # Evaluate every one of these before deciding: `all()` short-circuits,
        # and a formset left unvalidated loses its errors, so the reader fixes
        # one problem, submits, and meets the next one.
        trip_ok = form.is_valid()
        formset_ok = [item[2].is_valid() for item in formsets]
        if trip_ok and all(formset_ok):
            with transaction.atomic():
                # commit=True, so the travelers m2m is saved with it —
                # save_m2m() only exists on a commit=False form.
                form.save()
                _add_new_traveler(trip, traveler_form)
                for _key, _label, formset in formsets:
                    formset.save()
            messages.success(request, f"Saved “{trip.name}”.")
            return redirect("trips:trip_detail", pk=trip.pk)

    return render(
        request,
        "trips/trip_form.html",
        {
            "form": form,
            "traveler_form": traveler_form,
            "formsets": formsets,
            "trip": trip,
            "days": _days_with_counts(trip),
            "is_create": False,
        },
    )


@login_required
def trip_delete(request, pk):
    """Hide a trip. POST only for the change, GET to confirm.

    Soft, not real: see ``Trip.soft_delete``. The confirmation page is a GET
    rather than a bare button so the destructive step is always two requests.
    """
    trip = _readable_trip(request, pk, "delete")

    if request.method == "POST":
        trip.soft_delete()
        messages.success(
            request,
            f"Deleted “{trip.name}”. Nothing was removed — a staff member can "
            "restore it from the admin.",
        )
        return redirect("trips:trip_list")

    return render(request, "trips/trip_confirm_delete.html", {"trip": trip})


@login_required
def trip_restore(request, pk):
    """Undo a soft delete. POST only, and staff only.

    This is the one place that deliberately does *not* resolve through
    ``Trip.objects.visible_to``. That queryset is the whole reason the trip is
    deleted — it hides soft-deleted rows from everyone, staff included — so
    looking the trip up through it would make this view unreachable by
    construction.

    A deleted trip is still invisible to non-staff, including here: the
    queryset is emptied for them so they get the same 404 as for a pk that never
    existed, rather than a 403 that would confirm a trip is sitting there
    deleted. A live trip is a 404 too, because there is nothing to restore.
    """
    if request.method != "POST":
        return redirect("trips:trip_list")
    candidates = Trip.objects.deleted()
    if not (request.user.is_staff or request.user.is_superuser):
        candidates = candidates.none()
    trip = get_object_or_404(candidates, pk=pk)
    if not trip.can(request.user, "restore"):
        raise PermissionDenied
    trip.restore()
    messages.success(request, f"Restored “{trip.name}”.")
    return redirect(reverse("trips:trip_detail", args=[trip.pk]))


# ---------------------------------------------------------------------------
# Per-day editing
#
# A day owns its meals and sections, so it gets its own pages rather than more
# tables on the trip edit page. The day is always reached through its trip, so
# the permission and 404 rules are the ones the trip already established — there
# is no path to a day whose trip the reader cannot see.
# ---------------------------------------------------------------------------


def _editable_day(request, trip_pk, day_pk=None):
    """Resolve the parent trip, then a day on it.

    The trip comes first so the answer is a 404 when the trip is unreachable,
    not a 403 when a day cannot be edited. There is no `can_edit` capability for
    a day on its own: editing a day is editing its trip, so it is `edit` on the
    trip and nothing more, and inventing a second capability would only create a
    way for the two to disagree.
    """
    trip = _readable_trip(request, trip_pk, "edit")
    if day_pk is None:
        return trip, None
    day = get_object_or_404(Day.objects.filter(trip=trip), pk=day_pk)
    return trip, day


@login_required
def day_create(request, trip_pk):
    """Add a day to a trip.

    Blank `travelers` is the default and means the whole group is together,
    which is what most days are — so the field is never required.

    There are no meals on this page. A meal needs a saved day to hang off, and
    creating the day first to get one would break the all-or-nothing save the
    trip edit page sets up. So a new day starts empty and meals are added on the
    edit page that follows — the same save-then-fill-the-blank-row loop the
    formsets already use, rather than a special case.
    """
    trip, _ = _editable_day(request, trip_pk)
    form = DayForm(request.POST or None, trip=trip)

    if request.method == "POST":
        form = DayForm(request.POST, trip=trip)
        if form.is_valid():
            day = form.save(commit=False)
            day.trip = trip
            day.save()
            form.save_m2m()
            messages.success(request, f"Added day {day.day_number}.")
            return redirect(
                reverse("trips:trip_edit", args=[trip.pk]) + f"#day-{day.pk}"
            )

    return render(
        request,
        "trips/day_form.html",
        {"form": form, "trip": trip, "is_create": True},
    )


@login_required
def day_edit(request, trip_pk, pk):
    """Change a day and its meals in one submit.

    Meals are a formset here for the same reason they are not a formset on the
    trip page: a meal belongs to a day, and its day number is part of reading
    it. Atomic for the same reason too — a day whose meals saved but whose theme
    did not is a worse state than a rejected save.
    """
    trip, day = _editable_day(request, trip_pk, pk)
    form = DayForm(request.POST or None, instance=day, trip=trip)
    meal_formset = MealFormSet(request.POST or None, instance=day)

    if request.method == "POST":
        day_ok = form.is_valid()
        meals_ok = meal_formset.is_valid()
        if day_ok and meals_ok:
            with transaction.atomic():
                form.save()
                meal_formset.save()
            messages.success(request, f"Saved day {day.day_number}.")
            return redirect(
                reverse("trips:trip_edit", args=[trip.pk]) + f"#day-{day.pk}"
            )

    return render(
        request,
        "trips/day_form.html",
        {
            "form": form,
            "meal_formset": meal_formset,
            "trip": trip,
            "day": day,
            "sections": _day_sections(day),
            # dicts, not the raw (value, label) tuples from `choices`, so the
            # template can say `st.value` rather than `st.0` — and so an empty
            # value can never reach `{% url %}` and fail to reverse.
            "section_types": [
                {"value": value, "label": label}
                for value, label in Section.Type.choices
            ],
            "is_create": False,
        },
    )


@login_required
def day_delete(request, trip_pk, pk):
    """Delete a day, its meals and its sections.

    This is a *hard* delete, unlike a trip. Soft delete exists so a whole trip's
    content cannot vanish on one misclick; a day inside a trip the reader can
    still see is recoverable by re-entering it, and a `deleted_at` on `Day` would
    have to be honoured by every read path including the detail page's prefetch
    for no gain. The confirmation page spells that out rather than leaving the
    reader to work out that sections go with it.
    """
    trip, day = _editable_day(request, trip_pk, pk)

    if request.method == "POST":
        number = day.day_number
        linked_tasks = day.booking_tasks.count()
        day.delete()
        note = (
            f" {linked_tasks} booking task(s) that pointed at it were kept."
            if linked_tasks
            else ""
        )
        messages.success(
            request,
            f"Deleted day {number}, along with its meals and sections.{note}",
        )
        return redirect(reverse("trips:trip_edit", args=[trip.pk]))

    return render(
        request,
        "trips/day_confirm_delete.html",
        {
            "trip": trip,
            "day": day,
            "meal_count": day.meals.count(),
            "section_count": day.sections.count(),
            "linked_tasks": day.booking_tasks.count(),
        },
    )


# ---------------------------------------------------------------------------
# Sections
#
# A section's payload shape depends on its type, so sections are edited on their
# own page with a form chosen by that type, rather than in a table formset where
# every row would have to show every possible field.
# ---------------------------------------------------------------------------


@login_required
def section_create(request, trip_pk, day_pk, section_type):
    """Create a section of a given type, then edit its payload.

    The type arrives in the URL rather than in a select on the page, so creating
    a section is one link rather than a form plus a page. It is still validated
    against `Section.Type`: an unknown type in a hand-written URL would otherwise
    build a section with no payload form and fail on save.
    """
    trip, day = _editable_day(request, trip_pk, day_pk)
    if section_type not in Section.Type.values:
        raise Http404

    if request.method == "POST":
        return _save_section(request, trip, day, None, section_type)

    # A fresh, unsaved section so the page has something to render; `order`
    # defaults to the end rather than to 0, which would sort it to the top.
    section = Section(day=day, section_type=section_type, order=day.sections.count())
    payload_form = section_payload_form(section_type, content={})
    return render(
        request,
        "trips/section_form.html",
        _section_context(trip, day, section, payload_form, is_create=True),
    )


@login_required
def section_edit(request, trip_pk, day_pk, pk):
    """Edit a section's metadata and its typed payload in one save.

    An unknown `section_type` — one written by a newer importer than this UI —
    is reported rather than refused. The row is still there and still renders on
    the detail page, so turning the section page into a 500 would make the rest
    of the day unreachable through the only link that leads to it.
    """
    trip, day = _editable_day(request, trip_pk, day_pk)
    section = get_object_or_404(Section.objects.filter(day=day), pk=pk)

    if request.method == "POST":
        return _save_section(request, trip, day, section, section.section_type)

    payload_form = section_payload_form(
        section.section_type, content=section.content
    )
    return render(
        request,
        "trips/section_form.html",
        _section_context(trip, day, section, payload_form, is_create=False),
    )


def _section_context(trip, day, section, payload_form, *, is_create):
    """Context for the section page, successful or re-rendered.

    One helper so a validation failure and a first render cannot drift — the
    re-render after a bad POST is the case that silently loses a field or a
    heading when the two paths are written separately.

    `payload_form` is None for a type this UI has no form for, which the
    template renders as an explanation instead of an empty form.
    """
    return {
        "trip": trip,
        "day": day,
        "section": section,
        "form": SectionForm(instance=section),
        "payload_form": payload_form,
        "options_formset": getattr(payload_form, "options", None),
        "unsupported_type": None if payload_form is not None else section.section_type,
        "is_create": is_create,
    }


def _save_section(request, trip, day, section, section_type):
    """Validate metadata + payload together and write both in one transaction.

    `section` is None to create. The type is never taken from the payload form —
    it chose the payload form, so a post that disagreed would be a post editing
    a type it never rendered. It comes from the URL, which on edit is the type
    already stored.

    The instance is built *before* the form so `save(commit=False)` writes onto
    it. Passing `instance=None` and building one afterwards quietly loses every
    metadata field, because the form fills a different instance than the one
    saved.
    """
    if section is None:
        section = Section(day=day, section_type=section_type)

    metadata_form = SectionForm(request.POST, instance=section)
    payload_form = section_payload_form(
        section_type, request.POST, content=section.content
    )

    # A type this UI has no payload form for can still have its title and icon
    # changed. Refusing would contradict the page, which offers exactly that.
    metadata_ok = metadata_form.is_valid()
    if payload_form is not None:
        payload_ok = payload_form.is_valid()
        if metadata_ok and payload_ok:
            with transaction.atomic():
                metadata_form.save(commit=False)
                # Content is replaced only by a form that actually manages it.
                # An unsupported type leaves the stored payload byte-identical.
                section.content = payload_form.to_content()
                section.save()
            messages.success(request, "Saved section.")
            return _after_section_save(trip, day, section)
    elif metadata_ok:
        with transaction.atomic():
            metadata_form.save()
        messages.success(request, "Saved section.")
        return _after_section_save(trip, day, section)

    return render(
        request,
        "trips/section_form.html",
        {
            **_section_context(
                trip, day, section, payload_form, is_create=section.pk is None
            ),
            "form": metadata_form,
        },
    )


def _after_section_save(trip, day, section):
    return redirect(
        reverse("trips:day_edit", args=[trip.pk, day.pk]) + f"#section-{section.pk}"
    )


@login_required
def section_delete(request, trip_pk, day_pk, pk):
    """Delete a section.

    A hard delete, same reasoning as a day: the row is one block of content
    inside a day that is otherwise intact, and there is no `deleted_at` on
    `Section` for the detail page's prefetch to have to honour.
    """
    trip, day = _editable_day(request, trip_pk, day_pk)
    section = get_object_or_404(Section.objects.filter(day=day), pk=pk)

    if request.method == "POST":
        section.delete()
        messages.success(request, "Deleted section.")
        return redirect(reverse("trips:day_edit", args=[trip.pk, day.pk]))

    return render(
        request,
        "trips/section_confirm_delete.html",
        {"trip": trip, "day": day, "section": section},
    )


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------
#
# A comment is reached by *what it is about*, not by a trip id. The URLs name the
# kind of target (`trip`, `day`, `section`, `task`) and its pk, and the view
# resolves that to an object and then to the trip it belongs to. Nothing is
# trusted from the POST beyond the body of the text.
# --------------------------------------------------------------------------


def _comment_target(kind, pk):
    """The object a comment URL refers to, or ``None`` if the name is unknown.

    Deliberately does *not* check access. Every caller needs the target before
    it can know which trip to check access against, and returning a 404 from
    here would mean deciding visibility on an object whose trip is not yet known.
    """
    model = COMMENT_TARGET_KINDS.get(kind)
    if model is None:
        return None
    return get_object_or_404(model, pk=pk)


def _commentable(request, kind, pk, action="comment"):
    """Resolve a comment target and check the user may ``action`` on its trip.

    404 for a target whose trip the user cannot read, including a target that
    does not exist and a target the user has no grant on — those are the same
    answer, because the difference is itself information about someone else's
    trip. 403 only once the trip is readable and the action is still refused.
    """
    target = _comment_target(kind, pk)
    trip = comment_trip(target)
    if trip is None:
        # Either an unsupported kind, or a target that resolves to no trip.
        raise Http404
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=trip.pk)
    if not trip.can(request.user, action):
        raise PermissionDenied
    return target, trip


def _comment_thread_anchor(kind, object_id):
    """The ``id`` of a thread, which must match ``templates/trips/_comments.html``."""
    return f"comments-{kind}-{object_id}"


def _comment_return_url(target):
    """Where to go after posting or editing about ``target``.

    Always the **detail** page, anchored to the thread — never the editing page
    the target belongs to. Those need ``edit``, and the whole point of the
    ``commentor`` role is that it is below ``editor``: returning someone who can
    post but not edit to ``day_edit`` would answer their POST with a 403, so they
    would never see the comment they had just written. An anchor into the
    detail page keeps the thread they were talking about on screen.

    Derived from the target, never taken from a ``next`` field in the POST. A
    redirect-to parameter is an open redirect the moment it can be a full URL,
    and the target already says exactly where the comment ended up.
    """
    trip = comment_trip(target)
    if trip is None:
        return reverse("trips:trip_list")
    kind = comment_kind(target)
    if kind is None:
        return reverse("trips:trip_detail", args=[trip.pk])
    return reverse("trips:trip_detail", args=[trip.pk]) + (
        "#" + _comment_thread_anchor(kind, target.pk)
    )


@login_required
def comment_create(request, kind, pk):
    """Post a comment on a trip, day, section or booking task.

    Comments are the one action a *viewer* with the commentor role can take, so
    the page it appears on does not need to be editable. That is why this is not
    part of the section or trip form: a read-only page still needs somewhere to
    talk about itself.
    """
    target, trip = _commentable(request, kind, pk)
    return_url = _comment_return_url(target)

    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(author=request.user, target=target)
            messages.success(request, "Comment added.")
            return redirect(return_url + f"#comment-{comment.pk}")
    else:
        form = CommentForm()

    return render(
        request,
        "trips/comment_form.html",
        {"form": form, "trip": trip, "target": target, "return_url": return_url},
    )


@login_required
def comment_edit(request, pk):
    """Edit or delete one comment.

    Reached by comment id alone, so the trip is resolved from the comment's own
    target rather than from the URL. A comment whose target has been deleted
    resolves to no trip and is a 404 for everyone — there is nowhere to show it,
    and leaving it reachable would be a comment with no context.
    """
    comment = get_object_or_404(Comment, pk=pk)
    trip = comment.trip()
    if trip is None:
        raise Http404
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=trip.pk)
    if not comment.can_edit(request.user):
        raise PermissionDenied

    target = comment.content_object
    return_url = _comment_return_url(target)

    if request.method == "POST":
        if request.POST.get("action") == "delete":
            comment.delete()
            messages.success(request, "Comment deleted.")
            return redirect(return_url)

        # Captured before the form is bound. `CommentForm(instance=comment)`
        # writes onto this very instance, so comparing after the save compares
        # the body against itself and every edit would look like a no-op.
        original_body = comment.body
        form = CommentForm(request.POST, instance=comment)
        if form.is_valid():
            saved = form.save()
            # Stamped only when the text actually changed, so "edited" never
            # appears on a comment that was posted once and never touched again.
            if saved.body != original_body:
                saved.edited_at = django_timezone.now()
                saved.save(update_fields=["edited_at"])
            messages.success(request, "Comment updated.")
            return redirect(return_url + f"#comment-{saved.pk}")
    else:
        form = CommentForm(instance=comment)

    return render(
        request,
        "trips/comment_form.html",
        {
            "form": form,
            "trip": trip,
            "target": target,
            "return_url": return_url,
            "comment": comment,
        },
    )


def public_trip_detail(request, token):
    """The public, non-detailed page for a trip. No account required.

    Unauthenticated on purpose — the roadmap's public view is for showing the
    shape of a trip to somebody who does not have one — so the *only* thing
    granting access is possession of an unguessable token. Which means three
    things follow, and all three are load-bearing:

    - The trip is looked up by token, never by pk. A pk here would make every
      trip enumerable by anyone willing to count.
    - No token, or an unknown one, is a 404. Not a 403: a 403 would confirm a
      token exists. Not a redirect to login either, because there is nothing to
      log into — the page is public, so an expired link should simply be gone.
    - A soft-deleted trip is a 404 as well, token notwithstanding. ``Trip
      .objects.public()`` filters those out, so a link somebody shared before a
      deletion stops working on its own.

    The template gets ``public``, a plain dict from ``trips/public.py``. It
    never receives the ``Trip``, so there is no ``{{ trip.name }}`` to reach for
    — the omission cannot be forgotten in the template, only in the allowlist,
    which is tested.
    """
    # ``public_token`` is unique, so this is one row or none; the token having
    # been set at all is what means "this trip has a public page".
    trip = get_object_or_404(
        Trip.objects.public(token).prefetch_related("days__meals", "days__sections")
    )
    return render(
        request,
        "trips/public_trip.html",
        {"public": public_trip(trip), "trip_title": trip.public_title},
    )


@login_required
def traveler_profile(request):
    """The signed-in person's own travel profile and rewards programs.

    There is no pk in the URL: the row is the one linked to ``request.user``,
    so there is no other traveler this view can be pointed at. That is the
    whole of the access rule for this page — ``Traveler.is_private_to`` is
    trivially true for one's own row, and staff edit everybody else's in the
    admin. An account with no linked traveler (the signals should prevent it)
    is a 404 rather than a page that would create one by guessing.

    Atomic like ``trip_edit``: the profile and every membership row validate
    before anything is written.
    """
    traveler = get_object_or_404(Traveler, user=request.user)
    form = TravelerProfileForm(request.POST or None, instance=traveler)
    memberships = RewardsMembershipFormSet(
        request.POST or None, instance=traveler, prefix="memberships"
    )

    if request.method == "POST":
        profile_ok = form.is_valid()
        memberships_ok = memberships.is_valid()
        if profile_ok and memberships_ok:
            with transaction.atomic():
                form.save()
                memberships.save()
            messages.success(request, "Saved your travel profile.")
            return redirect("trips:traveler_profile")

    return render(
        request,
        "trips/traveler_profile.html",
        {"form": form, "memberships": memberships, "traveler": traveler},
    )
