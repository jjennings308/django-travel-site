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

from datetime import date
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as django_timezone


from .forms import (
    TripExpenseForm,
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
from . import itinerary
from .models import (
    TripExpense,
    BookingTask,
    Comment,
    Day,
    Lodging,
    Meal,
    Section,
    Traveler,
    Trip,
    TripGrant,
    TripRole,
    TransportLeg,
    TripActivity,
    Confirmation,
    ConfirmationLink,
    ItemLink,
    can_create_trip,
    role_capabilities,
    comment_kind,
    comment_trip,
    COMMENT_TARGET_KINDS,
)
from apps.core.pwa import offline_cache_key

from .dashboard import build_dashboard
from .public import public_trip


def _visible_capabilities(user, trips):
    """Attach per-row capabilities to trips the user can already read.

    ``Trip.capabilities_for`` costs a query a call, and this is a list page, so
    calling it per row would be a query per trip. Instead the user's grant roles
    for every listed trip are read in one query and fed to the same
    ``role_capabilities`` rule ``capabilities_for`` uses. Staff get everything
    without a grant.

    ``ListCapabilityEquivalenceTests`` in test_edit_views.py pins this against
    ``capabilities_for`` for every role, owned and not.
    """
    trips = list(trips)
    staff = user.is_staff or user.is_superuser
    roles = (
        {}
        if staff
        else dict(
            TripGrant.objects.filter(
                user=user, trip__in=[trip.pk for trip in trips]
            ).values_list("trip_id", "role")
        )
    )
    for trip in trips:
        if staff:
            allowed = {"edit", "delete"}
        else:
            allowed = role_capabilities(
                roles.get(trip.pk), owns=trip.created_by_id == user.pk
            )
        trip.list_capabilities = {
            "edit": "edit" in allowed,
            "delete": "delete" in allowed,
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


def _day_back(request, trip, day):
    """Where the day page returns: ``next`` when it's on this site (Edit trip passes its own
    address), else the day on the trip page, which opens it (trip-page UX plan, U5)."""
    return _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}")


def _day_workshop(trip, day):
    """The day page's "On this day" list (U5): the same timeline as the trip page for this one
    day, then its sections and food ideas, each item with its confirmation numbers and linked
    contacts/notes. An edit page, so a handful of plain queries is fine here."""
    from django.contrib.contenttypes.models import ContentType
    from .models import Contact, ItemLink, TripInfo
    day.day_legs = list(trip.transport.filter(date=day.date)) if day.date else []
    for leg in day.day_legs:
        leg.order_label = f"order {leg.order}"  # untimed legs run in this order
    day.ordered_activities = list(day.activities.select_related("poi"))
    day.ordered_meals = list(day.meals.order_by("order", "id"))
    sections = list(_day_sections(day))
    itinerary.timeline([day])
    items = {}
    for model, objs in ((TransportLeg, day.day_legs), (TripActivity, day.ordered_activities),
                        (Meal, day.ordered_meals), (Section, sections)):
        type_id = ContentType.objects.get_for_model(model).pk
        for obj in objs:
            obj.confirmation_list, obj.refs = [], []
            items[(type_id, obj.pk)] = obj
    for link in ConfirmationLink.objects.filter(confirmation__trip=trip).select_related("confirmation"):
        item = items.get((link.content_type_id, link.object_id))
        if item is not None:
            item.confirmation_list.append(link.confirmation)
    sources = {(ContentType.objects.get_for_model(Contact).pk, c.pk): c for c in trip.contacts.all()}
    sources.update({(ContentType.objects.get_for_model(TripInfo).pk, i.pk): i for i in trip.infos.all()})
    for link in ItemLink.objects.filter(trip=trip):
        item = items.get((link.target_type_id, link.target_id))
        source = sources.get((link.source_type_id, link.source_id))
        if item is not None and source is not None:
            item.refs.append(source)
    return {"sections": sections, "timeline": day.timeline, "any_time": day.any_time,
            "food_ideas": day.food_ideas}


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
    # Upcoming and current trips first (soonest first), then finished ones (latest first).
    upcoming = sorted((t for t in trips if not t.is_completed), key=lambda t: (t.start_date, t.name))
    past = sorted((t for t in trips if t.is_completed), key=lambda t: (t.end_date, t.name), reverse=True)
    return render(
        request,
        "trips/trip_list.html",
        {
            "trips": trips,
            "upcoming": upcoming,
            "past": past,
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


def _trip_page_queryset(user):
    """The trip page's one big prefetch, shared with the PDF booklet (``trip_pdf``) so
    both render from the same rows. See ``trip_detail`` for why each relation is here."""
    return (
        Trip.objects.visible_to(user)
        .prefetch_related(
            # Only the *leaf* relations carry to_attr. Putting one on "days" as
            # well silently breaks the chain: the sections get fetched, but
            # Django attaches them to a different set of Day instances than the
            # ones trip.ordered_days holds, so the template's for loop over
            # ordered_sections quietly iterates nothing. Prefetching just the
            # leaves is what makes the template loop work at all.
            # Each day's city rides along with the days query (no extra query).
            Prefetch("days", queryset=Day.objects.select_related("city")),
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
            # A day's activities (tours, timed entries, tables…) with their place and who's
            # going: two fixed queries.
            Prefetch(
                "days__activities",
                queryset=TripActivity.objects.select_related("poi").prefetch_related("travelers"),
                to_attr="ordered_activities",
            ),
            # The template calls day.is_split and day.roster_summary per day, and
            # is_split only avoids a query when "travelers" is already in the
            # prefetch cache. Without this the page costs one extra query per
            # day — 17 for the Europe trip, purely to ask whether a roster is
            # set.
            "days__travelers",
            "cities",  # the trip's catalogue cities (chips under the title): one query
            "lodging",
            "transport",
            "confirmations",
            # What each confirmation covers (trip-items plan, Phase B): four fixed queries,
            # however many confirmations or items. Legs and stays get their confirmations from
            # these lists in Python (_attach_confirmations) rather than a reverse prefetch each.
            Prefetch("confirmations__links", queryset=ConfirmationLink.objects.select_related("content_type")),
            "confirmations__travelers",
            # Tickets and documents on them (site roadmap R5): one fixed query.
            "confirmations__files",
            "contacts",
            # Contacts and info notes linked to items (trip-page UX plan, U4): two fixed queries.
            "infos",
            Prefetch("item_links", queryset=ItemLink.objects.select_related("source_type", "target_type")),
            "booking_tasks",
            # A decision's options (U6): one fixed query for every task's.
            "booking_tasks__options",
            "travelers",
        )
        .annotate(
            outstanding_task_count=Count(
                "booking_tasks", filter=Q(booking_tasks__done=False), distinct=True
            )
        )
    )


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
    trip = get_object_or_404(_trip_page_queryset(request.user), pk=pk)
    comments, comments_by_target = _trip_comments(trip, request.user)
    # One capabilities lookup for every action the page offers: each trip.can()
    # is a query, and this page pins its query count (QueryCountTests).
    # The same query also brings the reader's grant, for the ⋯ menu's change-email switch (R7).
    capabilities, my_grant = trip.capabilities_and_grant(request.user)
    stray_legs = itinerary.place_legs(trip)
    _attach_confirmations(trip)
    from . import booking_tasks
    booking_tasks.attach(trip, suggestions="edit" in capabilities)
    from .travel_tables import has_pending
    travel_tables_pending = "edit" in capabilities and has_pending(trip.days.all())
    # The page shell (trip-page UX plan, U2): where you sleep each night, the Overview row per
    # day and the day to open on arrival — all from the rows above, no queries.
    days = list(trip.days.all())
    stray_stays = itinerary.attach_stays(days, list(trip.lodging.all()))
    not_booked = booking_tasks.not_booked(trip)
    open_tasks = [task for task in trip.booking_tasks.all() if not task.done]
    open_decisions = [task for task in open_tasks if task.kind == task.Kind.DECIDE]
    itinerary.overview(days, not_booked, open_tasks)
    itinerary.timeline(days)
    itinerary.attach_links(trip, days)
    opened = itinerary.open_day(days, django_timezone.localdate())
    return render(
        request,
        "trips/trip_detail.html",
        {
            "trip": trip,
            "days": days,
            "open_day_pk": opened.pk if opened else None,
            "stray_legs": stray_legs,
            "stray_stays": stray_stays,
            "open_tasks": open_tasks,
            "open_decisions": open_decisions,
            "travel_tables_pending": travel_tables_pending,
            "not_booked": not_booked,
            "confirmation_groups": confirmation_groups(trip),
            "leg_modes": TransportLeg.Mode.choices,
            "trip_comments": comments.get(("trip", trip.pk), []),
            "comments_by_target": comments_by_target,
            "can_comment": "comment" in capabilities,
            "can_edit": "edit" in capabilities,
            "can_delete": "delete" in capabilities,
            # The offline copy (site roadmap R6): this person's cache name, and fresh static
            # files in dev, where their names aren't hashed.
            "offline_key": offline_cache_key(request.user),
            "my_grant": my_grant,
            "offline_debug": settings.DEBUG,
        },
    )


@login_required
def trip_pdf(request, pk):
    """The trip as a downloadable booklet (apps/trips/pdf.py): cover and days at a glance,
    one section per day, then confirmations, stays, contacts and what's still to book. Anyone
    who can see the trip; never part of the public view (it carries confirmation numbers)."""
    import logging
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from django.utils.text import slugify
    from . import booking_tasks
    from .pdf import PdfUnavailable, booklet_context, render_pdf

    trip = get_object_or_404(_trip_page_queryset(request.user), pk=pk)
    stray_legs = itinerary.place_legs(trip)
    _attach_confirmations(trip)
    booking_tasks.attach(trip)
    itinerary.attach_links(trip, list(trip.days.all()))
    html = render_to_string("trips/pdf/booklet.html", {
        "trip": trip, "stray_legs": stray_legs, "confirmation_groups": confirmation_groups(trip),
        "printed": django_timezone.localdate(), **booklet_context(trip),
    }, request=request)
    try:
        pdf = render_pdf(html, base_url=request.build_absolute_uri("/"))
    except PdfUnavailable as exc:
        logging.getLogger(__name__).error("Trip PDF unavailable: %s", exc)
        messages.error(request, "The PDF booklet can't be made on this server yet (its PDF libraries are "
                                "missing). Use your browser's Print → Save as PDF for now.")
        return redirect("trips:trip_detail", pk=trip.pk)
    response = HttpResponse(pdf, content_type="application/pdf")
    filename = f"{slugify(trip.public_title or trip.name) or 'trip'}-itinerary.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


CONFIRMATION_GROUPS = (("flight", "Flights"), ("train", "Trains"), ("stay", "Stays"), ("activity", "Activities"),
                       ("meal", "Meals"), ("other", "Other"))


def _attach_confirmations(trip):
    """Resolve each prefetched confirmation's links against the items the page already has
    (legs, stays, the days' sections and meals; no query): every item gets its
    ``confirmation_list`` (chips; ``leg.stage`` "booked") and every confirmation its
    ``_items`` (Quick reference's description, kind and date)."""
    days = list(trip.days.all())
    items = {("transportleg", leg.pk): leg for leg in trip.transport.all()}
    items.update({("lodging", stay.pk): stay for stay in trip.lodging.all()})
    for day in days:
        for section in getattr(day, "ordered_sections", []):
            section.day = day
            items[("section", section.pk)] = section
        for meal in getattr(day, "ordered_meals", []):
            meal.day = day
            items[("meal", meal.pk)] = meal
        for activity in getattr(day, "ordered_activities", []):
            activity.day = day
            items[("tripactivity", activity.pk)] = activity
    for item in items.values():
        item.confirmation_list = []
    for confirmation in trip.confirmations.all():
        confirmation._items = []
        for link in confirmation.links.all():
            item = items.get((link.content_type.model, link.object_id))
            if item is not None:
                confirmation._items.append(item)
                item.confirmation_list.append(confirmation)
        # Where its Reference row links to: its first item's card, or that item's day.
        first = confirmation.covered_items()[:1]
        confirmation.anchor = _item_anchor(first[0]) if first else ""


def _item_anchor(item):
    """The trip page id of an item's row or card, else of its day (itinerary.anchor)."""
    return itinerary.anchor(item)


def confirmation_groups(trip):
    """Quick reference, generated: [(title, [confirmation, ...])] grouped Flights / Trains /
    Stays / Meals / Other by what each covers, ordered by its first covered date; loose ones
    (covering nothing) last within Other. Uses the prefetched rows."""
    buckets = {key: [] for key, _title in CONFIRMATION_GROUPS}
    for confirmation in trip.confirmations.all():
        buckets[confirmation.kind].append(confirmation)
    groups = []
    for key, title in CONFIRMATION_GROUPS:
        items = sorted(buckets[key], key=lambda c: (c.first_date is None, c.first_date or date.min,
                                                    (c.label or c.confirmation_number).lower()))
        if items:
            groups.append((title, items))
    return groups


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


def _warn_if_ready_with_open_tasks(request, trip):
    """Status is a hand-set label; flag "Ready to go" while booking tasks are still open."""
    if trip.is_ready:
        open_tasks = trip.booking_tasks.filter(done=False).count()
        if open_tasks:
            messages.warning(
                request,
                f"“{trip.name}” is marked Ready to go but still has {open_tasks} booking "
                f"task{'s' if open_tasks != 1 else ''} outstanding.",
            )


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

        # A creator who can make a trip but cannot edit the result would create
        # something they cannot finish, or that vanishes from their own list. Give
        # them an editor grant on what they just made.
        TripGrant.objects.create(
            trip=trip, user=request.user, granted_by=request.user, role=TripRole.EDITOR
        )

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
    formsets = trip_subsection_formsets(trip, request.POST or None, initial=_stay_from_option(request, trip))

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
            for _key, _label, fs in formsets:
                for f in fs.forms:
                    back = getattr(f, "return_leg", None)
                    if back is not None:
                        messages.info(request, f"Added the return: {back.origin or '?'} → {back.destination or '?'}.")
            filled = sum(getattr(f, "days_filled", 0) for _key, _label, fs in formsets for f in fs.forms)
            if filled:
                messages.info(request, f"Filled in the city for {filled} day{'s' if filled != 1 else ''} from your stays; change any day trips by hand.")
            _warn_if_ready_with_open_tasks(request, trip)
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
            **_edit_trip_travel_and_bookings(trip),
        },
    )


def _stay_from_option(request, trip):
    """Edit trip's blank stay row pre-filled from a decision's chosen option
    (``?stay_from_option=<pk>``, U6): name from its title, notes from its detail and link.
    Nothing is saved until the editor saves the page."""
    from .models import TaskOption
    pk = request.GET.get("stay_from_option", "")
    if request.method != "GET" or not pk.isdigit():
        return None
    option = TaskOption.objects.filter(task__trip=trip, pk=pk).first()
    if option is None:
        return None
    notes = "\n".join(part for part in (option.detail, option.url) if part)
    return {"lodging": [{"name": option.title[:200], "notes": notes, "currency": option.currency or "USD"}]}


def _edit_trip_travel_and_bookings(trip):
    """Edit trip's "Travel by day" (each day's legs, the add-a-leg form, add a travel section)
    and "Bookings & confirmations" (every leg, stay and activity, plus sections and meals that
    have a confirmation, with what's attached; loose confirmations). The view page only shows
    them: all adding happens here."""
    from .models import CONFIRMABLE, item_label
    from .travel_tables import logistics_sections
    from apps.trips.logistics import proposed_legs
    days = list(trip.days.prefetch_related("sections").order_by("date", "day_number"))
    legs = list(trip.transport.all())
    stays = list(trip.lodging.all())
    attached = {}
    loose = []
    for confirmation in trip.confirmations.prefetch_related("links__content_type"):
        if not confirmation.links.all():
            loose.append(confirmation)
        for link in confirmation.links.all():
            attached.setdefault((link.content_type.model, link.object_id), []).append(confirmation)
    for day in days:
        day.edit_legs = [leg for leg in legs if leg.date == day.date]
        day.has_travel = any(s.section_type == Section.Type.TRAVEL for s in day.sections.all())
    rows = []
    for leg in legs:
        rows.append({"kind": "leg", "item": leg, "label": item_label(leg), "when": leg.date,
                     "what": leg.get_mode_display(), "confirmations": attached.get(("transportleg", leg.pk), [])})
    for stay in stays:
        rows.append({"kind": "stay", "item": stay, "label": stay.name, "when": stay.check_in, "what": "Stay",
                     "confirmations": attached.get(("lodging", stay.pk), [])})
    for activity in trip.activities.select_related("day"):
        rows.append({"kind": "activity", "item": activity, "label": activity.title, "when": activity.day.date,
                     "what": activity.get_kind_display(),
                     "confirmations": attached.get(("tripactivity", activity.pk), [])})
    model_names = {"section": "section", "meal": "meal"}
    for kind, model_name in model_names.items():
        ids = [pk for (name, pk) in attached if name == model_name]
        for item in CONFIRMABLE[kind].objects.filter(pk__in=ids).select_related("day"):
            rows.append({"kind": kind, "item": item, "label": item_label(item), "when": item.day.date,
                         "what": "Meal" if kind == "meal" else "Plan",
                         "confirmations": attached[(model_name, item.pk)]})
    rows.sort(key=lambda r: (r["when"] is None, r["when"] or date.min))
    pending = any(any(p["strength"] == "arrow" for p in proposed_legs((s.content or {}).get("columns"),
                                                                        (s.content or {}).get("rows")))
                  for s in logistics_sections(trip))
    return {"travel_days": days, "booking_rows": rows, "loose_confirmations": loose,
            "leg_modes": TransportLeg.Mode.choices, "travel_tables_pending": pending}


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
@require_POST
def trip_share(request, pk):
    """Turn the trip's public link on (editors and staff). Idempotent: an existing
    link is kept, so pressing Share again never breaks one already sent."""
    trip = _readable_trip(request, pk, "edit")
    trip.enable_public()
    messages.success(request, "Sharing is on. Anyone with the link sees the trip's name, dates and outline, nothing else.")
    return redirect("trips:trip_detail", pk=trip.pk)


@login_required
@require_POST
def trip_notify(request, pk):
    """Turn this person's emails about changes to the trip on or off (site roadmap R7)."""
    trip = get_object_or_404(Trip.objects.visible_to(request.user), pk=pk)
    grant = get_object_or_404(TripGrant, trip=trip, user=request.user)
    grant.notify_changes = request.POST.get("on") == "1"
    grant.save(update_fields=["notify_changes"])
    messages.success(request, "You'll get a daily email when this trip changes, and one straight away if a "
                              "journey's time changes in the week before it." if grant.notify_changes
                     else "No more emails about changes to this trip. You can turn them back on from the ⋯ menu.")
    return redirect("trips:trip_detail", pk=trip.pk)


@login_required
@require_POST
def trip_unshare(request, pk):
    """Turn the public link off; links already sent stop working."""
    trip = _readable_trip(request, pk, "edit")
    trip.revoke_public()
    messages.success(request, "Sharing is off. The old link no longer works.")
    return redirect("trips:trip_detail", pk=trip.pk)


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
            return redirect(_day_back(request, trip, day))

    return render(
        request,
        "trips/day_form.html",
        {
            "form": form,
            "meal_formset": meal_formset,
            "trip": trip,
            "day": day,
            "back": _day_back(request, trip, day),
            "leg_modes": TransportLeg.Mode.choices,
            **_day_workshop(trip, day),
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
        **_section_legs_context(section),
    }


def _section_legs_context(section):
    """A travel section's legs (edited as legs, not rows) and the quick add; a logistics
    table with "A → B" rows gets a link to turn them into legs (trip-items plan, Phase D)."""
    if section is None or section.pk is None:
        return {}
    if section.section_type == Section.Type.TRAVEL:
        return {"section_legs": list(section.legs.all()), "leg_modes": TransportLeg.Mode.choices}
    if section.section_type == Section.Type.LOGISTICS_TABLE:
        from .logistics import proposed_legs
        content = section.content or {}
        return {"turn_into_legs": bool(proposed_legs(content.get("columns"), content.get("rows")))}
    return {}


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
        reverse("trips:day_edit", args=[trip.pk, day.pk]) + "#on-this-day"
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
            # One anchor, the comment itself: return_url already ends in the thread's "#…", and a
            # second "#" would point at nothing, so the trip page couldn't open the day it's in.
            return redirect(return_url.split("#")[0] + f"#comment-{comment.pk}")
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
            # One anchor, the comment itself: return_url already ends in the thread's "#…", and a
            # second "#" would point at nothing, so the trip page couldn't open the day it's in.
            return redirect(return_url.split("#")[0] + f"#comment-{saved.pk}")
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


def _default_currency(trip):
    """The trip's most-used expense currency, else its lodging's, else USD."""
    from django.db.models import Count as _Count
    used = trip.expenses.values("currency").annotate(n=_Count("id")).order_by("-n").first()
    if used:
        return used["currency"]
    lodging = trip.lodging.exclude(currency="").first()
    return lodging.currency if lodging else "USD"


@login_required
def trip_budget(request, pk):
    """Costs on a trip, totals per currency, each traveller's share and who owes whom.

    Anyone who can see the trip sees it; editors add costs here (POST). Separate
    from the detail page, whose query count is pinned.
    """
    from .budget import summarize
    trip = _readable_trip(request, pk, "view")
    can_edit = trip.can(request.user, "edit")
    form = None
    if can_edit:
        form = TripExpenseForm(request.POST or None, trip=trip,
                               initial={"currency": _default_currency(trip), "spent_on": trip.start_date})
        if request.method == "POST" and form.is_valid():
            expense = form.save(commit=False)
            expense.trip, expense.created_by = trip, request.user
            expense.save()
            form.save_m2m()
            messages.success(request, f"Added “{expense.description}”.")
            return redirect("trips:trip_budget", pk=trip.pk)
    elif request.method == "POST":
        raise PermissionDenied
    expenses = list(trip.expenses.select_related("paid_by", "day").prefetch_related("shared_with")
                    .order_by("spent_on", "created_at"))
    everyone = list(trip.travelers.all())
    lodging_estimate = {}
    for stay in trip.lodging.all():
        if stay.nightly_rate:
            lodging_estimate[stay.currency] = lodging_estimate.get(stay.currency, 0) + stay.nightly_rate * stay.nights
    return render(request, "trips/trip_budget.html", {
        "trip": trip, "expenses": expenses, "summary": summarize(expenses, everyone), "form": form,
        "can_edit": can_edit, "everyone": everyone, "lodging_estimate": sorted(lodging_estimate.items()),
    })


@login_required
def expense_edit(request, pk, expense_pk):
    trip = _readable_trip(request, pk, "edit")
    expense = get_object_or_404(TripExpense, pk=expense_pk, trip=trip)
    form = TripExpenseForm(request.POST or None, instance=expense, trip=trip)
    if request.method == "POST":
        if "delete" in request.POST:
            expense.delete()
            messages.success(request, f"Removed “{expense.description}”.")
            return redirect("trips:trip_budget", pk=trip.pk)
        if form.is_valid():
            form.save()
            messages.success(request, "Saved.")
            return redirect("trips:trip_budget", pk=trip.pk)
    return render(request, "trips/expense_form.html", {"trip": trip, "form": form, "expense": expense})


# ---- photos ------------------------------------------------------------------------------
@login_required
def trip_photos(request, pk):
    """The trip's shared photo album. Anyone who can see the trip sees it; commentors and
    editors add photos (POST). A separate page, so the detail page's query count holds."""
    from apps.media_app.forms import MAX_PHOTOS, MultipleImageField
    from django import forms as dj_forms

    class PhotoForm(dj_forms.Form):
        photos = MultipleImageField(label="Add photos", help_text=f"Up to {MAX_PHOTOS} at a time; JPEG, PNG, WebP or iPhone HEIC. Large photos are scaled down.")

    trip = _readable_trip(request, pk, "view")
    can_add = trip.can(request.user, "comment")
    can_edit = trip.can(request.user, "edit")
    form = PhotoForm(request.POST or None, request.FILES or None) if can_add else None
    if request.method == "POST":
        if not can_add:
            raise PermissionDenied
        if form.is_valid() and form.cleaned_data["photos"]:
            added = trip.add_photos(form.cleaned_data["photos"], request.user)
            messages.success(request, f"Added {len(added)} photo{'s' if len(added) != 1 else ''}.")
            return redirect("trips:trip_photos", pk=trip.pk)
    photos = list(trip.photos())
    return render(request, "trips/trip_photos.html", {
        "trip": trip, "photos": photos, "form": form, "can_add": can_add, "can_edit": can_edit,
        "cover_id": trip.album.cover_image_id if trip.album_id else None,
    })


def _trip_photo(request, pk, media_pk):
    from apps.media_app.models import AlbumMedia
    trip = _readable_trip(request, pk, "view")
    item = get_object_or_404(AlbumMedia.objects.select_related("media"), album_id=trip.album_id, media_id=media_pk)
    return trip, item.media


@login_required
@require_POST
def trip_photo_delete(request, pk, media_pk):
    """The person who added a photo, or an editor, may remove it."""
    trip, media = _trip_photo(request, pk, media_pk)
    if media.uploaded_by_id != request.user.pk and not trip.can(request.user, "edit"):
        raise PermissionDenied
    trip.remove_photo(media)
    messages.success(request, "Photo removed.")
    return redirect("trips:trip_photos", pk=trip.pk)


@login_required
@require_POST
def trip_photo_cover(request, pk, media_pk):
    """Editors choose the album's cover (shown in My adventures)."""
    trip, media = _trip_photo(request, pk, media_pk)
    if not trip.can(request.user, "edit"):
        raise PermissionDenied
    trip.album.cover_image = media
    trip.album.save(update_fields=["cover_image"])
    messages.success(request, "Cover photo set.")
    return redirect("trips:trip_photos", pk=trip.pk)


# ---- map ---------------------------------------------------------------------------------
def _trip_stops(trip):
    """(stops, others, legs) for the trip map.

    stops: the days' cities in date order, consecutive repeats merged, as dicts
    {city, first, last, days} (Day.city is where you spend the day). legs: transport legs with
    both a from and a to city, in departure order. others: the trip's other cities and
    the legs' cities that aren't a stop, by name."""
    stops = []
    for day in trip.days.filter(city__isnull=False).select_related("city__country").order_by("date"):
        if stops and stops[-1]["city"].pk == day.city_id:
            stops[-1]["last"] = day
            stops[-1]["days"] += 1
        else:
            stops.append({"city": day.city, "first": day, "last": day, "days": 1})
    legs = list(trip.transport.filter(origin_city__isnull=False, destination_city__isnull=False)
                .select_related("origin_city__country", "destination_city__country"))  # Meta order: date, then time
    shown = {s["city"].pk for s in stops}
    others = {}
    for city in trip.cities.select_related("country"):
        others.setdefault(city.pk, city)
    for leg in legs:
        for city in (leg.origin_city, leg.destination_city):
            others.setdefault(city.pk, city)
    others = sorted((c for pk, c in others.items() if pk not in shown), key=lambda c: c.name)
    return stops, others, legs


@login_required
def trip_map(request, pk):
    """The trip's places on a map: numbered stops in day order joined by a line, plus its
    other cities. A separate page, so the printed detail page and its query count hold."""
    trip = _readable_trip(request, pk, "view")
    stops, others, legs = _trip_stops(trip)
    return render(request, "trips/trip_map.html", {
        "trip": trip, "stops": stops, "others": others, "legs": legs, "can_edit": trip.can(request.user, "edit"),
        "stays": list(trip.lodging.select_related("city").order_by("check_in")),
    })


@login_required
def trip_map_data(request, pk):
    """GeoJSON for trip_map (provider-neutral). Never part of the public view."""
    from django.http import JsonResponse
    trip = _readable_trip(request, pk, "view")
    stops, others, legs = _trip_stops(trip)

    def feature(city, **props):
        return {"type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(city.longitude), float(city.latitude)]},
                "properties": {"name": city.name, "url": reverse("locations:city_detail", args=[city.slug]), **props}}

    def when(stop):
        first, last = stop["first"].date, stop["last"].date
        span = f"{first:%b} {first.day}" if first == last else f"{first:%b} {first.day} – {last:%b} {last.day}"
        return f"{span} · {stop['days']} day{'s' if stop['days'] != 1 else ''}, {stop['city'].country.name}"

    features = [feature(s["city"], order=n, subtitle=when(s), layer="cities") for n, s in enumerate(stops, start=1)]
    features += [feature(c, subtitle=f"{c.country.name} · on this trip", layer="cities") for c in others]
    for stay in trip.lodging.select_related("city").order_by("check_in"):
        # Name, place and dates only: never the confirmation number, rate or notes.
        position = stay.map_position
        if position is None:
            continue
        nights = stay.nights
        dates = f"{stay.check_in:%b} {stay.check_in.day} – {stay.check_out:%b} {stay.check_out.day}"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(position[1]), float(position[0])]},
            "properties": {
                "layer": "stays", "marker": "stay", "name": stay.name,
                "subtitle": " · ".join(p for p in (
                    f"{dates} ({nights} night{'s' if nights != 1 else ''})",
                    stay.city.name if stay.city_id else "",
                    "" if stay.latitude is not None else "pin on the city centre") if p),
            },
        })
    for leg in legs:  # Times through the leg's own local-time helpers (never |date on a converted time).
        what = " ".join(p for p in (leg.operator, leg.service_number) if p)
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": [
                [float(leg.origin_city.longitude), float(leg.origin_city.latitude)],
                [float(leg.destination_city.longitude), float(leg.destination_city.latitude)]]},
            "properties": {
                "layer": "legs",
                "mode": leg.mode,
                "planned": leg.is_planned,
                "name": f"{leg.get_mode_display()}: {leg.origin_city.name} → {leg.destination_city.name}",
                "subtitle": " · ".join(p for p in (what, (
                    f"{leg.date:%a, %b} {leg.date.day} · planned, no times yet" if leg.is_planned and leg.date
                    else "planned, no times yet" if leg.is_planned
                    else f"{leg.departure_local_date} {leg.departure_local_str}"), leg.notes[:80] if leg.is_planned else "") if p),
            },
        })
    return JsonResponse({"type": "FeatureCollection", "features": features})


# ---- logistics table -> planned legs -------------------------------------------------------
@login_required
def section_to_legs(request, trip_pk, day_pk, pk):
    """One logistics table's travel rows, reviewed as legs (editors only): each row links to
    the day's existing leg or becomes a planned one, and the table becomes a travel section.
    Nothing is saved before confirming; times are never guessed."""
    trip, day = _editable_day(request, trip_pk, day_pk)
    section = get_object_or_404(Section.objects.filter(day=day, section_type=Section.Type.LOGISTICS_TABLE)
                                .select_related("day"), pk=pk)
    return _review_travel_tables(
        request, trip, [section], back=f"{reverse('trips:trip_detail', args=[trip.pk])}#day-{day.day_number}",
        heading="Turn these rows into legs",
        subtitle=f"Day {day.day_number} · {day.date:%a, %b} {day.date.day} · “{section.title or 'Logistics'}”.")


@login_required
def trip_travel_review(request, pk):
    """Every logistics table of the trip at once (editors only): one review instead of one
    per day. Same rules as ``section_to_legs``."""
    from . import travel_tables
    trip = _readable_trip(request, pk, "edit")
    return _review_travel_tables(
        request, trip, travel_tables.logistics_sections(trip),
        back=reverse("trips:trip_detail", args=[trip.pk]), heading="Turn travel tables into legs",
        subtitle="Every table on this trip with “A → B” rows, by day.")


def _rough_text(value):
    """A timedelta as the review form's "45 min" / "2 h 30 min" ("" for None)."""
    if not value:
        return ""
    hours, minutes = divmod(int(value.total_seconds() // 60), 60)
    return f"{hours} h {minutes} min" if hours and minutes else f"{hours} h" if hours else f"{minutes} min"


def _review_travel_tables(request, trip, sections, back, heading, subtitle):
    from apps.locations.models import City
    from . import travel_tables
    from .forms import LegProposalFormSet

    city_for = travel_tables.city_finder(trip)
    plans = travel_tables.plan(trip, sections, city_for=city_for)
    pairs = [(section_plan, row) for section_plan in plans for row in section_plan.rows]
    initial = [{
        "include": row["include"], "section": section_plan.section.pk, "row": row["row"], "date": row["date"],
        "mode": row["mode"], "origin": row["origin"], "destination": row["destination"],
        "origin_city": row["origin_city"].pk if row["origin_city"] else None,
        "destination_city": row["destination_city"].pk if row["destination_city"] else None,
        "operator": row["operator"], "duration": _rough_text(row["duration"]), "notes": row["notes"],
    } for section_plan, row in pairs]
    # The city choices are the trip's cities (all when it has none), plus any catalogue city a
    # row matched, which still has to be choosable.
    choices = None
    if city_for.trip_cities:
        extra = {i[k] for i in initial for k in ("origin_city", "destination_city") if i[k]}
        choices = City.objects.filter(pk__in={c.pk for c in city_for.trip_cities} | extra) \
            .select_related("country").order_by("name")
    formset = LegProposalFormSet(request.POST or None, initial=initial, prefix="legs",
                                 form_kwargs={"cities": choices})

    if request.method == "POST" and formset.is_valid():
        # Only rows the plan has (this trip's tables, as they are now) can be carried out.
        planned = {(section_plan.section.pk, row["row"]) for section_plan, row in pairs}
        chosen = {}
        for form in formset:
            data = form.cleaned_data
            key = (data.get("section"), data.get("row"))
            if data.get("include") and key in planned:
                chosen[key] = data
        result = travel_tables.apply(trip, plans, chosen)
        made, linked = len(result["created"]), len(result["linked"])
        if made or linked:
            parts = []
            if made:
                parts.append(f"made {made} planned leg{'s' if made != 1 else ''}")
            if linked:
                parts.append(f"linked {linked} existing leg{'s' if linked != 1 else ''}")
            tables = result["sections"]
            messages.success(request, f"{' and '.join(parts).capitalize()}; {tables} table{'s' if tables != 1 else ''} "
                                      "became travel sections. Add times once they're booked.")
        else:
            messages.info(request, "No legs made.")
        return redirect(back)

    rows = [(form, row) for form, (_plan, row) in zip(formset.forms, pairs)]
    groups, start = [], 0
    for section_plan in plans:
        groups.append((section_plan, rows[start:start + len(section_plan.rows)]))
        start += len(section_plan.rows)
    return render(request, "trips/section_to_legs.html", {
        "trip": trip, "formset": formset, "groups": groups, "rows": rows,
        "back": back, "heading": heading, "subtitle": subtitle,
    })


# ---- legs: edit in place, quick add from a day ------------------------------------------
def _back(request, fallback):
    """The ``next`` page if it's on this site, else ``fallback``."""
    from django.utils.http import url_has_allowed_host_and_scheme
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                                  require_https=request.is_secure()):
        return target
    return fallback


def _leg_back(trip, leg):
    day = trip.days.filter(date=leg.date).first() if leg.date else None
    anchor = f"#day-{day.day_number}" if day else "#getting-around"
    return reverse("trips:trip_detail", args=[trip.pk]) + anchor


@login_required
def leg_edit(request, pk, leg_pk):
    """One leg on its own page: route, schedule, details and where on its day it's shown."""
    from .forms import LegEditForm
    trip = _readable_trip(request, pk, "edit")
    leg = get_object_or_404(trip.transport.all(), pk=leg_pk)
    form = LegEditForm(request.POST or None, instance=leg)
    if request.method == "POST" and form.is_valid():
        leg = form.save()
        messages.success(request, f"Saved {leg.origin} → {leg.destination}.")
        if form.return_leg is not None:
            messages.info(request, f"Added the return: {form.return_leg.origin} → {form.return_leg.destination}.")
        return redirect(_back(request, _leg_back(trip, leg)))
    from .forms import COMMON_ZONE_SUGGESTIONS
    return render(request, "trips/leg_form.html", {
        "trip": trip, "leg": leg, "form": form, "next": _back(request, _leg_back(trip, leg)),
        "zone_suggestions": COMMON_ZONE_SUGGESTIONS,
        **_item_confirmations_context(request, trip, "leg", leg),
        **_item_links_context(trip, "leg", leg),
        "open_tasks": list(leg.booking_tasks.filter(done=False)),
    })


@login_required
def leg_delete(request, pk, leg_pk):
    trip = _readable_trip(request, pk, "edit")
    leg = get_object_or_404(trip.transport.all(), pk=leg_pk)
    back = _back(request, _leg_back(trip, leg))
    if request.method == "POST":
        label = f"{leg.origin} → {leg.destination}"
        leg.delete()
        messages.success(request, f"Deleted {label}.")
        return redirect(back)
    return render(request, "trips/leg_confirm_delete.html", {"trip": trip, "leg": leg, "next": back})


@login_required
@require_POST
def leg_quick_add(request, pk, day_pk):
    """A planned leg typed like a table row, on a day (and in one of its travel sections)."""
    from django.db.models import Max
    from apps.approval_system.models import ApprovalStatus
    from apps.locations.models import City
    from .forms import LegQuickAddForm
    from .logistics import match_city
    trip, day = _editable_day(request, pk, day_pk)
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}")
    form = LegQuickAddForm(request.POST)
    if not form.is_valid():
        errors = "; ".join(f"{form.fields[f].label}: {' '.join(e)}" if f in form.fields else " ".join(e)
                           for f, e in form.errors.items())
        messages.error(request, f"The leg wasn't added. {errors}")
        return redirect(back)
    data = form.cleaned_data
    section = None
    if data.get("section"):
        section = get_object_or_404(Section.objects.filter(day=day, section_type=Section.Type.TRAVEL),
                                    pk=data["section"])
    trip_cities = list(trip.cities.all())
    catalogue = list(City.objects.filter(approval_status=ApprovalStatus.APPROVED))
    origin_city = match_city(data["origin"], trip_cities) or match_city(data["origin"], catalogue)
    destination_city = match_city(data["destination"], trip_cities) or match_city(data["destination"], catalogue)
    last = trip.transport.filter(date=day.date).aggregate(m=Max("order"))["m"]
    leg = TransportLeg.objects.create(
        trip=trip, date=day.date, section=section, mode=data["mode"], origin=data["origin"],
        destination=data["destination"], origin_city=origin_city, destination_city=destination_city,
        est_duration=data["est_duration"], notes=data["notes"], order=(last or 0) + 1)
    for city in (origin_city, destination_city):
        if city is not None:
            trip.cities.add(city)
    messages.success(request, f"Added {leg.origin} → {leg.destination} (planned).")
    return redirect(back)


@login_required
@require_POST
def day_add_travel(request, pk, day_pk):
    """Give a day a travel section ("Getting around") to place its legs in."""
    from django.db.models import Max
    trip, day = _editable_day(request, pk, day_pk)
    last = day.sections.aggregate(m=Max("order"))["m"]
    Section.objects.create(day=day, section_type=Section.Type.TRAVEL, title="Getting around",
                           order=(last or 0) + 1, content={})
    messages.success(request, f"Added a travel section to day {day.day_number}.")
    return redirect(_back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}"))


# ---- activities on a day (tours, timed entries, tickets, tables, car hire) ----------------
@login_required
def activity_edit(request, pk, day_pk, activity_pk=None):
    """Add or edit an activity on a day (editors). Its confirmations are added on the same
    page, like a leg's."""
    from .forms import TripActivityForm
    trip, day = _editable_day(request, pk, day_pk)
    activity = None
    if activity_pk is not None:
        activity = get_object_or_404(TripActivity.objects.filter(trip=trip, day=day), pk=activity_pk)
    initial = {}
    if activity is None and request.GET.get("from_option", "").isdigit():
        # Pre-filled from a decision's option (U6, trips:option_add); nothing saved until submit.
        from .models import TaskOption
        option = TaskOption.objects.filter(task__trip=trip, pk=request.GET["from_option"]).first()
        if option is not None:
            initial = {"title": option.title, "notes": "\n".join(p for p in (option.detail, option.url) if p),
                       "est_cost": option.est_cost, "currency": option.currency}
    form = TripActivityForm(request.POST or None, instance=activity or TripActivity(trip=trip, day=day),
                            initial=initial, trip=trip)
    back = _back(request, reverse("trips:day_edit", args=[trip.pk, day.pk]) + "#activities")
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Saved {saved.title}.")
        if activity is None:  # stay on its page so a confirmation can be added straight away
            return redirect(reverse("trips:activity_edit", args=[trip.pk, day.pk, saved.pk]) + "?next=" + quote(back))
        return redirect(back)
    context = {"trip": trip, "day": day, "activity": activity, "form": form, "next": back}
    if activity is not None:
        context.update(_item_confirmations_context(request, trip, "activity", activity))
        context.update(_item_links_context(trip, "activity", activity))
    return render(request, "trips/activity_form.html", context)


@login_required
def activity_delete(request, pk, day_pk, activity_pk):
    trip, day = _editable_day(request, pk, day_pk)
    activity = get_object_or_404(TripActivity.objects.filter(trip=trip, day=day), pk=activity_pk)
    back = _back(request, reverse("trips:day_edit", args=[trip.pk, day.pk]) + "#activities")
    if request.method == "POST":
        title = activity.title
        activity.delete()
        messages.success(request, f"Deleted {title}. Its confirmations are kept.")
        return redirect(back)
    return render(request, "trips/activity_confirm_delete.html",
                  {"trip": trip, "day": day, "activity": activity, "next": back})


# ---- content clean-up review (trip-page UX plan, U7) -----------------------------------------
@login_required
def trip_tidy(request, pk):
    """Suggestions for text that repeats something with a home elsewhere (editors). Nothing
    changes until an editor ticks suggestions and applies them; "Not this" dismisses one for good."""
    from . import tidying
    trip = _readable_trip(request, pk, "edit")
    found = tidying.suggestions(trip)
    if request.method == "POST":
        if request.POST.get("dismiss"):
            tidying.dismiss(trip, request.POST["dismiss"])
            messages.info(request, "That suggestion won't come back.")
            return redirect(reverse("trips:trip_tidy", args=[trip.pk]))
        chosen = {key[len("pick-"):]: request.POST.get(f"act-{key[len('pick-'):]}", "")
                  for key in request.POST if key.startswith("pick-")}
        applied, skipped = tidying.apply(trip, found, chosen)
        if applied:
            messages.success(request, f"Applied {len(applied)} suggestion{'s' if len(applied) != 1 else ''}.")
        for suggestion, why in skipped:
            messages.warning(request, f"Skipped “{suggestion.before[:60]}”: {why}.")
        if not applied and not skipped:
            messages.info(request, "Nothing was ticked.")
        return redirect(reverse("trips:trip_tidy", args=[trip.pk]))
    groups = {}
    for suggestion in found:
        groups.setdefault(suggestion.day, []).append(suggestion)
    ordered = sorted(groups.items(), key=lambda item: (item[0] is None, item[0] or 0))
    return render(request, "trips/trip_tidy.html", {"trip": trip, "groups": ordered, "count": len(found)})


# ---- decisions: tasks with options (trip-page UX plan, U6) ----------------------------------
@login_required
def task_options(request, pk, task_pk):
    """A decision's options (editors): add, edit, reorder and delete them, and choose one (or
    none). Choosing creates nothing; the trip page then offers to add it as a stay or activity."""
    from .forms import TaskOptionFormSet
    trip = _readable_trip(request, pk, "edit")
    task = get_object_or_404(trip.booking_tasks.all(), pk=task_pk)
    formset = TaskOptionFormSet(request.POST or None, instance=task, prefix="options")
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + "#still-to-book")
    if request.method == "POST" and formset.is_valid():
        with transaction.atomic():
            formset.save()
            chosen = request.POST.get("chosen", "")
            task.options.update(chosen=False)
            if chosen.isdigit():
                task.options.filter(pk=chosen).update(chosen=True)
            elif chosen.startswith("new-"):
                # A row added in this same submit: its index among the formset's forms.
                index = chosen[4:]
                form = formset.forms[int(index)] if index.isdigit() and int(index) < len(formset.forms) else None
                if form is not None and form.instance.pk:
                    task.options.filter(pk=form.instance.pk).update(chosen=True)
            if task.kind != task.Kind.DECIDE and task.options.exists():
                task.kind = task.Kind.DECIDE
                task.save(update_fields=["kind"])
        messages.success(request, f"Saved the options for “{task.title}”.")
        return redirect(back)
    chosen_pk = next((o.pk for o in task.options.all() if o.chosen), None)
    return render(request, "trips/task_options.html", {"trip": trip, "task": task, "formset": formset,
                                                       "chosen_pk": chosen_pk, "next": back,
                                                       "days": list(trip.days.order_by("day_number"))})


@login_required
def option_add(request, pk, option_pk):
    """Add a decision's option as a stay or an activity (U6): redirects to Edit trip with the
    blank stay row pre-filled, or to the new-activity page of the task's day (or ``?day=``),
    pre-filled. Saves nothing itself."""
    from .models import TaskOption
    trip = _readable_trip(request, pk, "edit")
    option = get_object_or_404(TaskOption.objects.filter(task__trip=trip).select_related("task"), pk=option_pk)
    if request.GET.get("as") == "stay":
        return redirect(reverse("trips:trip_edit", args=[trip.pk]) + f"?stay_from_option={option.pk}#lodging")
    day_pk = request.GET.get("day") or option.task.day_id
    day = get_object_or_404(trip.days.all(), pk=day_pk) if day_pk else None
    if day is None:
        messages.info(request, "Pick the day it happens on.")
        return redirect(reverse("trips:task_options", args=[trip.pk, option.task_id]))
    back = reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}"
    return redirect(reverse("trips:activity_new", args=[trip.pk, day.pk])
                    + f"?from_option={option.pk}&next={quote(back)}")


# ---- contacts and info notes linked to items (trip-page UX plan, U4) -------------------------
def _item_links_context(trip, kind, item):
    """What an item's Contacts & info block needs (leg / activity pages and ``item_links``)."""
    from .forms import QuickContactForm, QuickInfoForm
    from .models import ItemLink, LINK_SOURCES
    from django.contrib.contenttypes.models import ContentType
    links = ItemLink.objects.filter(target_type=ContentType.objects.get_for_model(type(item)), target_id=item.pk)
    by_type = {ContentType.objects.get_for_model(model).pk: (key, model) for key, model in LINK_SOURCES.items()}
    linked = []
    for link in links:
        key, model = by_type[link.source_type_id]
        source = model.objects.filter(pk=link.source_id).first()
        if source is not None:
            linked.append({"kind": key, "obj": source})
    linked_keys = {(entry["kind"], entry["obj"].pk) for entry in linked}
    choices = [("contact", c) for c in trip.contacts.all() if ("contact", c.pk) not in linked_keys]
    choices += [("info", i) for i in trip.infos.all() if ("info", i.pk) not in linked_keys]
    return {"link_kind": kind, "link_item": item, "linked_refs": linked, "link_choices": choices,
            "contact_form": QuickContactForm(prefix="contact"), "info_form": QuickInfoForm(prefix="info")}


@login_required
def item_links(request, pk, kind, item_pk):
    """The contacts and info notes on one item — a leg, stay, activity, meal, section or day —
    added and removed here like its confirmations (editors). Unlinking never deletes."""
    from .forms import QuickContactForm, QuickInfoForm
    from .models import LINK_SOURCES, LINKABLE, Contact, ItemLink, TripInfo, item_label, item_trip_id
    model = LINKABLE.get(kind)
    if model is None:
        raise Http404
    trip = _readable_trip(request, pk, "edit")
    item = get_object_or_404(model.objects.all(), pk=item_pk)
    if item_trip_id(item) != trip.pk:
        raise Http404
    here = request.get_full_path()
    back = _back(request, reverse("trips:trip_edit", args=[trip.pk]) + "#contacts-info")
    context = {"trip": trip, "item_label": item_label(item), "next": back}
    if request.method == "POST":
        action = request.POST.get("action")
        if action in ("attach", "detach"):
            source_kind, _, source_pk = (request.POST.get("source") or "").partition(":")
            source_model = LINK_SOURCES.get(source_kind)
            if source_model is None or not source_pk.isdigit():
                raise Http404
            source = get_object_or_404(source_model.objects.filter(trip=trip), pk=source_pk)
            if action == "attach":
                ItemLink.link(source, item)
                messages.success(request, f"Added {source} to {item_label(item)}.")
            else:
                ItemLink.unlink(source, item)
                messages.success(request, f"Removed {source} from {item_label(item)} (it's kept in Reference).")
        elif action == "new_contact":
            form = QuickContactForm(request.POST, prefix="contact")
            if not form.is_valid():
                ctx = _item_links_context(trip, kind, item)
                ctx["contact_form"] = form
                return render(request, "trips/item_links.html", {**context, **ctx})
            contact = Contact.objects.create(trip=trip, **form.cleaned_data)
            ItemLink.link(contact, item)
            messages.success(request, f"Added {contact.name} to {item_label(item)}.")
        elif action == "new_info":
            form = QuickInfoForm(request.POST, prefix="info")
            if not form.is_valid():
                ctx = _item_links_context(trip, kind, item)
                ctx["info_form"] = form
                return render(request, "trips/item_links.html", {**context, **ctx})
            info = TripInfo.objects.create(trip=trip, **form.cleaned_data)
            ItemLink.link(info, item)
            messages.success(request, f"Added “{info.title}” to {item_label(item)}.")
        from django.utils.http import url_has_allowed_host_and_scheme
        return_to = request.POST.get("return_to") or ""
        if not url_has_allowed_host_and_scheme(return_to, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
            return_to = here
        return redirect(return_to)
    return render(request, "trips/item_links.html", {**context, **_item_links_context(trip, kind, item)})


def _source_edit(request, pk, form_class, model, source_pk, template, label):
    trip = _readable_trip(request, pk, "edit")
    instance = get_object_or_404(model.objects.filter(trip=trip), pk=source_pk) if source_pk else model(trip=trip)
    form = form_class(request.POST or None, instance=instance, trip=trip)
    back = _back(request, reverse("trips:trip_edit", args=[trip.pk]) + "#contacts-info")
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            saved = form.save()
            form.save_links()
        messages.success(request, f"Saved {label} “{saved}”.")
        return redirect(back)
    return render(request, template, {"trip": trip, "form": form, "obj": instance if source_pk else None,
                                      "next": back})


def _source_delete(request, pk, model, source_pk, label):
    trip = _readable_trip(request, pk, "edit")
    obj = get_object_or_404(model.objects.filter(trip=trip), pk=source_pk)
    back = _back(request, reverse("trips:trip_edit", args=[trip.pk]) + "#contacts-info")
    if request.method == "POST":
        name = str(obj)
        obj.delete()  # its links go with it (GenericRelation); the items stay
        messages.success(request, f"Deleted {label} “{name}”. The items it was on are kept.")
        return redirect(back)
    return render(request, "trips/source_confirm_delete.html", {"trip": trip, "obj": obj, "label": label,
                                                                 "next": back})


@login_required
def contact_edit(request, pk, contact_pk=None):
    """A contact's own page: its details and the items it's linked to (editors)."""
    from .forms import ContactEditForm
    from .models import Contact
    return _source_edit(request, pk, ContactEditForm, Contact, contact_pk, "trips/contact_form.html", "contact")


@login_required
def contact_delete(request, pk, contact_pk):
    from .models import Contact
    return _source_delete(request, pk, Contact, contact_pk, "contact")


@login_required
def info_edit(request, pk, info_pk=None):
    """An info note's own page: title, body, link and the items it's linked to (editors)."""
    from .forms import TripInfoForm
    from .models import TripInfo
    return _source_edit(request, pk, TripInfoForm, TripInfo, info_pk, "trips/info_form.html", "info note")


@login_required
def info_delete(request, pk, info_pk):
    from .models import TripInfo
    return _source_delete(request, pk, TripInfo, info_pk, "info note")


# ---- confirmations: attached to items like comments (trips:item_confirmations) ------------
@login_required
def confirmation_edit(request, pk, confirmation_pk=None):
    """A booking reference's own details. ``confirmation_new`` is for a loose one (insurance,
    a rail pass); others are added from their item."""
    from .forms import ConfirmationEditForm
    trip = _readable_trip(request, pk, "edit")
    confirmation = None
    if confirmation_pk is not None:
        confirmation = get_object_or_404(trip.confirmations.all(), pk=confirmation_pk)
    form = ConfirmationEditForm(request.POST or None, instance=confirmation or Confirmation(trip=trip), trip=trip)
    back = _back(request, reverse("trips:trip_edit", args=[trip.pk]) + "#bookings")
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Saved confirmation {saved.confirmation_number}.")
        return redirect(back)
    covers = []
    if confirmation is not None:
        from .models import confirmable_kind, item_label
        for item in confirmation.covered_items():
            covers.append({"label": item_label(item), "kind": confirmable_kind(item), "item": item})
    return render(request, "trips/confirmation_form.html", {
        "trip": trip, "form": form, "confirmation": confirmation, "next": back, "covers": covers,
    })


@login_required
def confirmation_delete(request, pk, confirmation_pk):
    trip = _readable_trip(request, pk, "edit")
    confirmation = get_object_or_404(trip.confirmations.all(), pk=confirmation_pk)
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + "#quick-reference")
    if request.method == "POST":
        number = confirmation.confirmation_number
        confirmation.delete()
        messages.success(request, f"Deleted confirmation {number}. The legs and stays it covered are kept.")
        return redirect(back)
    return render(request, "trips/confirmation_confirm_delete.html",
                  {"trip": trip, "confirmation": confirmation, "next": back})


def _item_confirmations_context(request, trip, kind, item):
    """What the confirmations block needs (leg page and ``item_confirmations``): the item's
    confirmations, the trip's others it could join, and the add form."""
    from .forms import AddConfirmationForm
    attached = list(Confirmation.for_item(item).prefetch_related("links__content_type", "files__uploaded_by"))
    others = [c for c in trip.confirmations.prefetch_related("links__content_type") if c not in attached]
    return {"confirm_kind": kind, "confirm_item": item, "attached": attached, "attachable": others,
            "add_form": AddConfirmationForm()}


@login_required
def item_confirmations(request, pk, kind, item_pk):
    """The confirmations on one item of the trip — a leg, a stay, a day's section or a meal —
    added and removed here, the way comments are on what they're about (editors only).
    Adding a number the trip already has links the item to that confirmation."""
    from . import booking_tasks
    from .forms import AddConfirmationForm
    from .models import CONFIRMABLE, item_label, item_trip_id
    model = CONFIRMABLE.get(kind)
    if model is None:
        raise Http404
    trip = _readable_trip(request, pk, "edit")
    item = get_object_or_404(model.objects.all(), pk=item_pk)
    if item_trip_id(item) != trip.pk:
        raise Http404
    here = request.get_full_path()
    back = _back(request, reverse("trips:trip_edit", args=[trip.pk]) + "#bookings")
    if request.method == "POST":
        before = booking_tasks.confirmed_items(trip)
        action = request.POST.get("action")
        if action == "detach":
            confirmation = get_object_or_404(trip.confirmations.all(), pk=request.POST.get("confirmation") or 0)
            confirmation.unlink(item)
            messages.success(request, f"Removed {confirmation.confirmation_number} from {item_label(item)} (it's kept).")
        elif action == "attach":
            confirmation = get_object_or_404(trip.confirmations.all(), pk=request.POST.get("confirmation") or 0)
            confirmation.link(item)
            messages.success(request, f"Added {confirmation.confirmation_number} to {item_label(item)}.")
        else:
            form = AddConfirmationForm(request.POST)
            if not form.is_valid():
                context = _item_confirmations_context(request, trip, kind, item)
                context["add_form"] = form
                return render(request, "trips/item_confirmations.html",
                              {"trip": trip, "item_label": item_label(item), "next": back, **context})
            data = form.cleaned_data
            existed = Confirmation.find_number(trip, data["confirmation_number"]) is not None
            confirmation = Confirmation.attach_number(trip, data["confirmation_number"], item,
                                                      provider=data["provider"], label=data["label"])
            messages.success(request, f"{'Linked' if existed else 'Added'} {confirmation.confirmation_number}"
                                      f"{' (already on this trip)' if existed else ''} to {item_label(item)}.")
        # Back to the page the block was on (the leg page posts its own address), else here.
        from django.utils.http import url_has_allowed_host_and_scheme
        return_to = request.POST.get("return_to") or ""
        if not url_has_allowed_host_and_scheme(return_to, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
            return_to = here
        return redirect(_task_offer_or(trip, booking_tasks.offer_for(trip, before), return_to))
    return render(request, "trips/item_confirmations.html", {
        "trip": trip, "item_label": item_label(item), "next": back,
        **_item_confirmations_context(request, trip, kind, item),
    })


def _task_offer_or(trip, tasks, back):
    """The "mark these tasks done?" page when an item just got its first confirmation and
    has open tasks (Phase E: offered, never ticked automatically); else ``back``."""
    if not tasks:
        return back
    from urllib.parse import urlencode
    return reverse("trips:task_offer", args=[trip.pk]) + "?" + urlencode(
        {"tasks": ",".join(str(t.pk) for t in tasks), "next": back})


@login_required
def task_offer(request, pk):
    """Offer to tick off the open tasks of items that were just confirmed (editors)."""
    trip = _readable_trip(request, pk, "edit")
    source = request.POST if request.method == "POST" else request.GET
    ids = [int(i) for i in source.get("tasks", "").split(",") if i.strip().isdigit()]
    tasks = list(trip.booking_tasks.filter(pk__in=ids, done=False))
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + "#quick-reference")
    if request.method == "POST":
        ticked = {int(i) for i in request.POST.getlist("done") if i.isdigit()}
        finished = [task for task in tasks if task.pk in ticked]
        for task in finished:
            task.done = True
            task.save(update_fields=["done"])
        if finished:
            messages.success(request, f"Marked {len(finished)} task{'s' if len(finished) != 1 else ''} done.")
        return redirect(back)
    if not tasks:
        return redirect(back)
    from . import booking_tasks
    for task in tasks:
        item = task.leg or task.stay or task.activity
        task.item_label = booking_tasks.label(item) if item else ""
    return render(request, "trips/task_offer.html", {"trip": trip, "tasks": tasks, "next": back,
                                                      "ids": ",".join(str(t.pk) for t in tasks)})


@login_required
@require_POST
def task_link(request, pk, task_pk):
    """Link a task to the leg or stay it's about (``leg`` / ``stay``), or dismiss the
    suggestion (``dismiss`` = the suggested item's name, remembered in the task's notes)."""
    from . import booking_tasks
    trip = _readable_trip(request, pk, "edit")
    task = get_object_or_404(trip.booking_tasks.all(), pk=task_pk)
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + "#still-to-book")
    if request.POST.get("leg"):
        task.leg, task.stay, task.activity = get_object_or_404(trip.transport.all(), pk=request.POST["leg"]), None, None
        task.save(update_fields=["leg", "stay", "activity"])
        messages.success(request, f"“{task.title}” is now about {booking_tasks.label(task.leg)}.")
    elif request.POST.get("stay"):
        task.stay, task.leg, task.activity = get_object_or_404(trip.lodging.all(), pk=request.POST["stay"]), None, None
        task.save(update_fields=["leg", "stay", "activity"])
        messages.success(request, f"“{task.title}” is now about {task.stay.name}.")
    elif request.POST.get("activity"):
        task.activity = get_object_or_404(trip.activities.all(), pk=request.POST["activity"])
        task.leg = task.stay = None
        task.save(update_fields=["leg", "stay", "activity"])
        messages.success(request, f"“{task.title}” is now about {task.activity.title}.")
    elif request.POST.get("dismiss", "").strip():
        line = BookingTask.NOT_ABOUT + request.POST["dismiss"].strip()[:200]
        task.notes = "\n".join(n for n in (task.notes.rstrip(), line) if n)
        task.save(update_fields=["notes"])
    return redirect(back)
