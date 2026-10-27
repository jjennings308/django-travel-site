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
from django.http import Http404, HttpResponseBadRequest
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
)
from . import budget, checklists, itinerary, route, trip_cities, trip_notes
from .models import (
    counts_q,
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
    TidyDismissal,
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


def _add_section_types():
    """The section types a day can be given, as the day page's buttons: Note and Travel notes (day-first
    plan P3; choices come from + Add's Options and + Choose one, P4). A logistics table is not offered
    either (E6): only the importer makes them; old ones still render and edit."""
    labels = {Section.Type.TRAVEL: "Travel notes"}
    order = (Section.Type.NOTE, Section.Type.TRAVEL)
    return [{"value": value, "label": labels.get(value, Section.Type(value).label)} for value in order]


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
    day.ordered_meals = list(day.meals.select_related("poi").order_by("order", "id"))
    sections = list(_day_sections(day).select_related("poi", "activity", "event"))
    from . import catalogue_links
    catalogue_links.attach_suggestions(trip, day.ordered_meals, sections)
    itinerary.timeline([day])
    # Stays (E1): checking out, checking in, or the night you're sleeping there — as on the trip page.
    stays = list(trip.lodging.filter(check_in__lte=day.date, check_out__gte=day.date).select_related("city")) if day.date else []
    for stay in stays:
        stay.workshop_label = ("Check in" if stay.check_in == day.date
                               else "Check out" if stay.check_out == day.date else "Sleeping")
    stays.sort(key=lambda stay: ("Check out", "Check in", "Sleeping").index(stay.workshop_label))
    items = {}
    for model, objs in ((TransportLeg, day.day_legs), (TripActivity, day.ordered_activities),
                        (Meal, day.ordered_meals), (Section, sections), (Lodging, stays)):
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
            "food_ideas": day.food_ideas, "day_stays": stays}


@login_required
@require_POST
def catalogue_link(request, trip_pk, day_pk, kind, item_pk):
    """Link a meal or section to a suggested catalogue place / activity, or say "Not this one"
    (site roadmap R18). The target must be among the trip's catalogue choices."""
    from . import catalogue_links
    trip, day = _editable_day(request, trip_pk, day_pk)
    model = catalogue_links.KINDS.get(kind)
    if model is None:
        raise Http404
    item = get_object_or_404(model.objects.filter(day=day), pk=item_pk)
    target_kind, target_pk = request.POST.get("target_kind", ""), request.POST.get("target", "")
    if not target_pk.isdigit() or target_kind not in ("poi", "activity", "event"):
        return HttpResponseBadRequest("Missing target.")
    if request.POST.get("dismiss"):
        TidyDismissal.objects.get_or_create(
            trip=trip, key=catalogue_links.dismissal_key(kind, item.pk, target_kind, int(target_pk)))
    elif catalogue_links.link(trip, item, target_kind, int(target_pk)):
        messages.success(request, f"Linked to {getattr(item, target_kind).name} in the catalogue.")
    else:
        messages.error(request, "That isn't a catalogue place or activity in this trip's cities.")
    return redirect(_back(request, reverse("trips:day_edit", args=[trip.pk, day.pk]) + "#on-this-day"))


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


def _target_comments(user, kind, obj):
    """One day's or section's comments, for its edit page in the item panel (P2: the Comments tab)."""
    content_type = ContentType.objects.get_for_model(COMMENT_TARGET_KINDS[kind])
    return list(Comment.objects.filter(content_type=content_type, object_id=obj.pk)
                .annotate_editable(user).select_related("author"))


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
                # Their catalogue place (with city) and activity ride along (R18; no extra query).
                queryset=Section.objects.select_related("poi__city", "activity", "event__related_activity",
                                                        "event__poi").order_by("order", "id"),
                to_attr="ordered_sections",
            ),
            Prefetch(
                "days__meals",
                queryset=Meal.objects.select_related("poi__city").order_by("order", "id"),
                to_attr="ordered_meals",
            ),
            # A day's activities (tours, timed entries, tables…) with their place and who's
            # going: two fixed queries.
            Prefetch(
                "days__activities",
                queryset=TripActivity.objects.select_related("poi", "event__related_activity", "event__poi")
                .prefetch_related("travelers"),
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
            # Checklists (site roadmap R9): three fixed queries — lists, items, per-person ticks.
            "checklists__items__ticks",
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
    context = _trip_page_context(request, trip)
    # The Ideas shelf (day-first plan P6): two queries, the whole page only (not a day's fragment).
    from . import ideas
    all_ideas = ideas.load(trip, request.user)
    shelf = [idea for idea in all_ideas if idea.on_shelf]
    for idea in shelf:  # "Add as an option" offers the undecided choices its kind fits (typed-choices T3)
        idea.fitting_groups = [group for group in context["open_groups"] if ideas.fits(idea, group)]
    context.update({"ideas": shelf, "idea_count": len(all_ideas), "idea_kinds": ideas.KINDS})
    return render(request, "trips/trip_detail.html", context)


QUICK_ADD_KINDS = [("travel", "Travel"), ("stay", "Stay"), ("do", "Do"), ("eat", "Eat"), ("note", "Note"),
                   ("options", "Options")]  # + Add's kind buttons (P3; Options, a "choose one", P4)


def _trip_page_context(request, trip):
    """Everything the trip page shows, from the prefetched ``trip`` (``_trip_page_queryset``): also
    what one day's fragment (``day_fragment``) and an item's read-only panel (``item_panel``) render,
    so the three can't drift (day-first plan, P2)."""
    comments, comments_by_target = _trip_comments(trip, request.user)
    # One capabilities lookup for every action the page offers: each trip.can()
    # is a query, and this page pins its query count (QueryCountTests).
    # The same query also brings the reader's grant, for the ⋯ menu's change-email switch (R7).
    capabilities, my_grant = trip.capabilities_and_grant(request.user)
    # "Choose one" groups (day-first plan P4): items in an undecided or unchosen option leave the
    # prefetched lists here, so everything below counts only what's decided. Three queries.
    from . import options as option_groups
    all_groups = option_groups.load(trip)
    open_groups = option_groups.attach(trip, list(trip.days.all()), request.user, groups=all_groups)
    stray_legs = itinerary.place_legs(trip)
    _attach_confirmations(trip)
    from . import booking_tasks
    booking_tasks.attach(trip, suggestions="edit" in capabilities)
    from .travel_tables import has_pending
    travel_tables_pending = "edit" in capabilities and has_pending(trip.days.all())
    # Decision to-dos still to turn into choices (P4): no query.
    from .day_first import pending_count
    notes_pending = pending_count(trip) if "edit" in capabilities else 0
    # The page shell (trip-page UX plan, U2): where you sleep each night, the Overview row per
    # day and the day to open on arrival — all from the rows above, no queries.
    days = list(trip.days.all())
    stray_stays = itinerary.attach_stays(days, list(trip.lodging.all()))
    not_booked = booking_tasks.not_booked(trip)
    open_tasks = [task for task in trip.booking_tasks.all() if not task.done]
    open_decisions = [task for task in open_tasks if task.kind == task.Kind.DECIDE]
    itinerary.overview(days, not_booked, open_tasks)
    option_groups.count_on_days(days)
    itinerary.timeline(days)
    itinerary.attach_links(trip, days)
    trip_notes.attach(trip, days)  # catalogue notes under linked items (catalogue-notes N2): one query
    # Their closed days and book-by dates (N3): no queries, counted in the days' ⚠ and the banner.
    note_warnings = itinerary.note_warnings(days, list(trip.booking_tasks.all()), django_timezone.localdate())
    for item in note_warnings["closed"] + note_warnings["book_ahead"]:
        item.anchor = itinerary.anchor(item)
    opened = itinerary.open_day(days, django_timezone.localdate())
    checklist_lists = checklists.attach(trip)
    return {
        "trip": trip,
        "days": days,
        "open_day_pk": opened.pk if opened else None,
        "route_runs": route.runs(days),
        "stray_legs": stray_legs,
        "stray_stays": stray_stays,
        "open_tasks": open_tasks,
        "open_decisions": open_decisions,
        "closed_items": note_warnings["closed"],
        "book_ahead_items": note_warnings["book_ahead"],
        "travel_tables_pending": travel_tables_pending,
        "notes_pending": notes_pending,
        "open_groups": open_groups,
        "decision_count": len(open_decisions) + len(open_groups),
        "option_groups": all_groups,
        # + Add's kind buttons (P3; Options, a "choose one", P4).
        "quick_add_kinds": QUICK_ADD_KINDS,
        "not_booked": not_booked,
        "confirmation_groups": confirmation_groups(trip),
        "checklists": checklist_lists,
        # An option's own estimate counts once chosen, and for every track of a split (P5).
        "cost_estimate": budget.estimate(trip, _reader_currency(request), extra=[
            (o.own_cost, o.currency) for g in all_groups for o in ([g.chosen] if g.chosen else []) + g.tracks
            if o.own_cost is not None]),
        "checklist_attention": checklists.attention(trip, checklist_lists),
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
    }


def _is_panel(request):
    """Rendered for the item panel on the trip page (``?panel=1``, day-first plan P2): the page's
    content without the site chrome (``trips/_panel_base.html``, chosen in ``base_trips.html``)."""
    return bool(request.GET.get("panel"))


@login_required
def day_fragment(request, pk, day_pk):
    """One day of the trip page on its own (``trips/partials/_day.html``, open), from the same
    context as the page, so the item panel can swap the day in after a save (P2). Anyone who can
    see the trip."""
    trip = get_object_or_404(_trip_page_queryset(request.user), pk=pk)
    context = _trip_page_context(request, trip)
    day = next((d for d in context["days"] if d.pk == day_pk), None)
    if day is None:
        raise Http404
    # The day's links and forms carry the trip page's address as their "next", as on the page.
    request.path = reverse("trips:trip_detail", args=[trip.pk])
    return render(request, "trips/partials/_day.html", {**context, "day": day, "open_day_pk": day.pk})


#: The item panel's kinds (P2): where each is found in the trip page's assembled days.
PANEL_KINDS = ("leg", "stay", "activity", "meal", "section", "day")


def _find_on_days(context, kind, item_pk):
    """(item, its day) from the trip page context, or (None, None)."""
    trip, days = context["trip"], context["days"]
    if kind == "day":
        day = next((d for d in days if d.pk == item_pk), None)
        return day, day
    if kind == "stay":
        stay = next((s for s in trip.lodging.all() if s.pk == item_pk), None)
        if stay is not None:
            return stay, next((d for d in days if d.date == stay.check_in), None)
    if kind == "leg":
        leg = next((leg for leg in trip.transport.all() if leg.pk == item_pk), None)
        if leg is not None:
            return leg, getattr(leg, "on_day", None)
    # An item inside an option (P4) has left the day's lists: it's in its option's items.
    plural = {"leg": "legs", "stay": "stays", "activity": "activities", "meal": "meals", "section": "sections"}[kind]
    for group in context.get("option_groups", []):
        for option in group.option_list:
            for item in option.items[plural]:
                if item.pk == item_pk:
                    return item, next((d for d in days if d.pk == group.day_id), None)
    if kind in ("leg", "stay"):
        return None, None
    for day in days:
        items = {"activity": getattr(day, "ordered_activities", []), "meal": getattr(day, "ordered_meals", []),
                 "section": getattr(day, "ordered_sections", [])}[kind]
        for item in items:
            if item.pk == item_pk:
                return item, day
    return None, None


@login_required
def item_panel(request, pk, kind, item_pk):
    """An item read-only, for the panel on the trip page (P2): readers (viewers, commentors) click a
    leg, stay, activity, meal, section or day and see it as the page shows it, with its notes
    (comments) where it has them. Editors get the item's own edit page in the panel instead."""
    if kind not in PANEL_KINDS:
        raise Http404
    trip = get_object_or_404(_trip_page_queryset(request.user), pk=pk)
    context = _trip_page_context(request, trip)
    item, day = _find_on_days(context, kind, item_pk)
    if item is None:
        raise Http404
    by_target = context["comments_by_target"]
    comments = by_target.get(kind, {}).get(item.pk, []) if kind in ("day", "section") else None
    request.path = reverse("trips:trip_detail", args=[trip.pk])
    return render(request, "trips/item_panel.html", {
        **context, "kind": kind, "item": item, "day": day, "panel_comments": comments,
        "can_edit": False,  # read-only, whoever opens it
    })


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
    from . import options as option_groups
    option_groups.attach(trip, list(trip.days.all()), request.user)  # only what counts, as on the page (P4)
    stray_legs = itinerary.place_legs(trip)
    _attach_confirmations(trip)
    booking_tasks.attach(trip)
    itinerary.attach_links(trip, list(trip.days.all()))
    trip_notes.attach(trip, list(trip.days.all()))
    itinerary.note_warnings(list(trip.days.all()), list(trip.booking_tasks.all()), django_timezone.localdate())
    html = render_to_string("trips/pdf/booklet.html", {
        "trip": trip, "stray_legs": stray_legs, "confirmation_groups": confirmation_groups(trip),
        "printed": django_timezone.localdate(), "checklists": checklists.attach(trip), **booklet_context(trip),
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

    form = TripForm(request.POST or None, user=request.user)
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
def trip_route(request, pk):
    """The route builder (day-first plan, P1; ``apps/trips/route.py``): rows of city + nights, in
    order, starting from the days' cities. Preview shows what saving would do (days to fill, days kept
    because they already have another city, legs, stays, a route that doesn't add up); Save does it in
    one transaction under one history line. Editors only."""
    from . import route as route_module
    from .forms import RouteFormSet
    trip = _readable_trip(request, pk, "edit")
    days = list(trip.days.select_related("city"))
    options = {"replace": False, "legs": True, "stays": True, "extend": False}
    route = None
    if request.method == "POST":
        formset = RouteFormSet(request.POST, form_kwargs={"trip": trip})
        options = {name: request.POST.get(name) == "on" for name in options}
        if formset.is_valid():
            stops = [(row["city"], row["nights"]) for row in formset.cleaned_data if row.get("city")]
            route = route_module.plan(trip, stops, days, list(trip.transport.all()), list(trip.lodging.all()),
                                      extend=options["extend"])
            if "save" in request.POST and stops:
                counts = route_module.apply(trip, route, replace=options["replace"], make_legs=options["legs"],
                                            make_stays=options["stays"])
                parts = [f"{counts['days'] + counts['new_days']} day{'s' if counts['days'] + counts['new_days'] != 1 else ''}"]
                if counts["legs"]:
                    parts.append(f"{counts['legs']} planned leg{'s' if counts['legs'] != 1 else ''}")
                if counts["stays"]:
                    parts.append(f"{counts['stays']} stay{'s' if counts['stays'] != 1 else ''} to book")
                messages.success(request, f"Route set: {route.summary}. Saved {', '.join(parts)}.")
                return redirect(reverse("trips:trip_detail", args=[trip.pk]) + "#days")
            # Preview: the same rows again, with room for more stops.
            formset = RouteFormSet(initial=[{"city": c, "nights": n} for c, n in stops],
                                   form_kwargs={"trip": trip})
    else:
        formset = RouteFormSet(initial=route_module.initial_stops(days, trip.end_date), form_kwargs={"trip": trip})
    return render(request, "trips/trip_route.html", {
        "trip": trip, "formset": formset, "route": route, "options": options,
    })


@login_required
def trip_edit(request, pk):
    """The old Edit trip address: Settings now (day-first plan P7)."""
    _readable_trip(request, pk, "edit")
    return redirect("trips:trip_settings", pk=pk)


@login_required
def trip_settings(request, pk):
    """The trip's settings (day-first plan P7; was Edit trip): name, dates, status, home currency,
    cities, notes and travellers, plus the days table and the trip-wide lists (loose confirmations,
    contacts & info, checklists). Everything on a day is added and edited from the trip page. When a
    save moves the dates so the days no longer fit, the editor is offered the days to add or remove."""
    trip = _readable_trip(request, pk, "edit")
    before = (trip.start_date, trip.end_date)
    form = TripForm(request.POST or None, instance=trip, user=request.user)
    traveler_form = AddTravelerForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # commit=True, so the travelers m2m is saved with it — save_m2m() only exists on a
            # commit=False form.
            form.save()
            trip_cities.sync(trip)
            _add_new_traveler(trip, traveler_form)
        messages.success(request, f"Saved “{trip.name}”.")
        _warn_if_ready_with_open_tasks(request, trip)
        if (trip.start_date, trip.end_date) != before:
            from . import day_fit
            found = day_fit.plan(trip)
            if found["missing"] or found["outside"]:
                return redirect("trips:trip_days_fit", pk=trip.pk)
        return redirect("trips:trip_detail", pk=trip.pk)

    from .forms import share_choices
    share_choices(form)  # one query per select list (R23)
    return render(
        request,
        "trips/trip_form.html",
        {
            "form": form,
            "traveler_form": traveler_form,
            "trip": trip,
            "days": _days_with_counts(trip),
            "is_create": False,
            "checklist_templates": checklists.templates(),
            # Counted in the query, not once per row (R23).
            "edit_contacts": trip.contacts.annotate(link_count=Count("item_links")),
            "edit_infos": trip.infos.annotate(link_count=Count("item_links")),
            "edit_checklists": trip.checklists.annotate(item_count=Count("items")),
            "loose_confirmations": trip.confirmations.filter(links__isnull=True),
        },
    )


@login_required
def trip_days_fit(request, pk):
    """Fit the days to the trip's dates (editors; P7): after Settings moves them, add days for the
    new dates and remove ones now outside — each ticked or not; nothing changes until saved."""
    from . import day_fit
    trip = _readable_trip(request, pk, "edit")
    found = day_fit.plan(trip)
    settings_url = reverse("trips:trip_settings", args=[trip.pk])
    if request.method == "POST":
        add = []
        for value in request.POST.getlist("add"):
            try:
                add.append(date.fromisoformat(value))
            except ValueError:
                pass
        remove = [int(v) for v in request.POST.getlist("remove") if v.isdigit()]
        made, removed = day_fit.apply(trip, add, remove)
        if made or removed:
            messages.success(request, " and ".join(part for part in (
                f"added {made} day{'s' if made != 1 else ''}" if made else "",
                f"removed {removed}" if removed else "") if part).capitalize() + ".")
        return redirect(settings_url + "#days")
    return render(request, "trips/trip_days_fit.html", {"trip": trip, **found, "settings_url": settings_url})


@login_required
def trip_bookings(request, pk):
    """Bookings (day-first plan P7): the trip's confirmations, what isn't booked yet and every journey
    and stay in date order, read-only; each line opens its item on the trip page (in the panel)."""
    trip = get_object_or_404(_trip_page_queryset(request.user), pk=pk)
    context = _trip_page_context(request, trip)
    every = _edit_trip_stays_and_legs(Trip.objects.get(pk=trip.pk))
    return render(request, "trips/trip_bookings.html", {**context, **every})


def _edit_trip_stays_and_legs(trip):
    """Bookings' read-only "All stays & legs" (E3, moved from Edit trip in P7): every stay and leg in date order with its
    confirmation numbers and its day, flagged when no day of the trip has its date; and the loose
    confirmations (insurance, a rail pass). A fixed handful of queries, whatever the trip's size."""
    from django.contrib.contenttypes.models import ContentType
    from .travel_tables import logistics_sections
    from apps.trips.logistics import proposed_legs
    days_by_date = {day.date: day for day in trip.days.all() if day.date}
    leg_type, stay_type = (ContentType.objects.get_for_model(TransportLeg).pk,
                           ContentType.objects.get_for_model(Lodging).pk)
    attached, loose = {}, []
    for confirmation in trip.confirmations.prefetch_related("links"):
        if not confirmation.links.all():
            loose.append(confirmation)
        for link in confirmation.links.all():
            attached.setdefault((link.content_type_id, link.object_id), []).append(confirmation)
    rows = []
    for leg in trip.transport.all():
        rows.append({"kind": "leg", "item": leg, "anchor": f"leg-{leg.pk}", "when": leg.date, "day": days_by_date.get(leg.date),
                     "what": leg.get_mode_display(), "label": f"{leg.origin} → {leg.destination}",
                     "detail": ("planned" + (f" · {leg.est_duration_str}" if leg.est_duration_str else ""))
                     if leg.is_planned else leg.departure_local_str,
                     "confirmations": attached.get((leg_type, leg.pk), [])})
    for stay in trip.lodging.all():
        rows.append({"kind": "stay", "item": stay, "anchor": f"stay-{stay.pk}", "when": stay.check_in,
                     "day": days_by_date.get(stay.check_in),
                     "what": "Stay", "label": stay.name,
                     "detail": f"{stay.nights} night{'s' if stay.nights != 1 else ''}",
                     "confirmations": attached.get((stay_type, stay.pk), [])})
    rows.sort(key=lambda r: (r["when"] is None, r["when"] or date.min, r["kind"] != "stay"))
    pending = any(any(p["strength"] == "arrow" for p in proposed_legs((s.content or {}).get("columns"),
                                                                        (s.content or {}).get("rows")))
                  for s in logistics_sections(trip))
    return {"item_rows": rows, "loose_confirmations": loose, "travel_tables_pending": pending}


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
                reverse("trips:trip_settings", args=[trip.pk]) + f"#day-{day.pk}"
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
    meal_formset = MealFormSet(request.POST or None, instance=day, form_kwargs={"trip": trip})

    if request.method == "POST":
        day_ok = form.is_valid()
        meals_ok = meal_formset.is_valid()
        if day_ok and meals_ok:
            with transaction.atomic():
                form.save()
                meal_formset.save()
                trip_cities.sync(trip)  # a meal's catalogue place brings its city (P1)
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
            "section_types": _add_section_types(),
            "quick_add_kinds": QUICK_ADD_KINDS,
            "is_create": False,
            "panel_comments": _target_comments(request.user, "day", day) if _is_panel(request) else None,
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
        return redirect(reverse("trips:trip_settings", args=[trip.pk]))

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
    a section is one link rather than a form plus a page. Only the types Add to this
    day offers are made (Note, Travel notes): a retired type (phase, callout, free
    text, choose your adventure) or a logistics table in a hand-written URL is a 404.
    """
    trip, day = _editable_day(request, trip_pk, day_pk)
    if section_type not in {t["value"] for t in _add_section_types()}:
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
    context = _section_context(trip, day, section, payload_form, is_create=False)
    if _is_panel(request):
        context["panel_comments"] = _target_comments(request.user, "section", section)
    return render(request, "trips/section_form.html", context)


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
        "form": SectionForm(instance=section, trip=trip),
        "payload_form": payload_form,
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
        return {"turn_into_legs": bool(proposed_legs(content.get("columns"), content.get("rows"))),
                "is_logistics_table": True}
    return {}


@login_required
@require_POST
def section_to_travel_notes(request, trip_pk, day_pk, pk):
    """Make a logistics table a travel section (edit-by-day plan E6): the same payload (columns and
    rows; the rows become its reference rows), so nothing is lost and its day's legs can be placed in
    it. Editors; "Turn into legs" stays the way to make rows into legs."""
    trip, day = _editable_day(request, trip_pk, day_pk)
    section = get_object_or_404(day.sections.filter(section_type=Section.Type.LOGISTICS_TABLE), pk=pk)
    section.section_type = Section.Type.TRAVEL
    section.save(update_fields=["section_type"])
    messages.success(request, f"“{section.title or 'The table'}” is now travel notes; its rows are kept as reference rows.")
    return redirect("trips:section_edit", trip_pk=trip.pk, day_pk=day.pk, pk=section.pk)


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

    metadata_form = SectionForm(request.POST, instance=section, trip=trip)
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
            return _after_section_save(request, trip, day, section)
    elif metadata_ok:
        with transaction.atomic():
            metadata_form.save()
        messages.success(request, "Saved section.")
        return _after_section_save(request, trip, day, section)

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


def _after_section_save(request, trip, day, section):
    """Back to ``next`` when it's on this site (the trip page's Edit link, the panel), else the
    day page's "On this day"."""
    return redirect(_back(request, reverse("trips:day_edit", args=[trip.pk, day.pk]) + "#on-this-day"))


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
        return redirect(_back(request, reverse("trips:day_edit", args=[trip.pk, day.pk])))

    return render(
        request,
        "trips/section_confirm_delete.html",
        {"trip": trip, "day": day, "section": section, "next": _back(request, "")},
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
    # Only what counts (day-first plan P4): nothing in an undecided or unchosen option is public.
    trip = get_object_or_404(
        Trip.objects.public(token).prefetch_related(
            Prefetch("days__meals", queryset=Meal.objects.filter(counts_q())),
            Prefetch("days__sections", queryset=Section.objects.filter(counts_q())))
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
    # "Add to my travel profile" from a catalogue program page (?program=<id>) fills the blank row.
    program_id = request.GET.get("program", "")
    memberships = RewardsMembershipFormSet(
        request.POST or None, instance=traveler, prefix="memberships",
        initial=[{"catalogue_program": int(program_id)}] if program_id.isdigit() else None
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


def _reader_currency(request):
    """The reader's preferred currency (Settings), already loaded by the theme middleware."""
    settings_obj = getattr(request.user, "settings", None)
    return (getattr(settings_obj, "preferred_currency", "") or "USD").upper()


@login_required
def trip_budget(request, pk, rate_formset=None):
    """Costs on a trip, totals per currency, each traveller's share and who owes whom.

    Anyone who can see the trip sees it; editors add costs here (POST) and keep the trip's own
    exchange rates under "Your own rates" (``trip_rates``, E3: moved here from Edit trip).
    Separate from the detail page, whose query count is pinned.
    """
    from .budget import summarize
    from .forms import TripRateFormSet
    trip = _readable_trip(request, pk, "view")
    can_edit = trip.can(request.user, "edit")
    if can_edit and rate_formset is None:
        rate_formset = TripRateFormSet(instance=trip, prefix="rates", form_kwargs={"trip": trip})
    form = None
    if can_edit:
        form = TripExpenseForm(request.POST if request.method == "POST" else None, trip=trip,
                               instance=TripExpense(trip=trip), initial={"spent_on": trip.start_date})
        if request.method == "POST" and form.is_valid():
            expense = form.save(commit=False)
            expense.trip, expense.created_by = trip, request.user
            expense.save()
            form.save_m2m()
            messages.success(request, f"Added “{expense.description}”.")
            return redirect("trips:trip_budget", pk=trip.pk)
    elif request.method == "POST":
        raise PermissionDenied
    own_rates = list(trip.rates.all())
    for rate in own_rates:
        rate.rate_text = f"{rate.rate.normalize():f}"  # 1.5 and 160, not 1.50000000 or 1.6E+2
    expenses = list(trip.expenses.select_related("paid_by", "day").prefetch_related("shared_with")
                    .order_by("spent_on", "created_at"))
    everyone = list(trip.travelers.all())
    # Totals in one currency (site roadmap R10): ?in=USD (default: the reader's currency), and
    # ?settle=1 to settle up in it too. Each cost converts at its own date's rate.
    from .budget import in_one_currency, rates_for
    target = (request.GET.get("in") or _reader_currency(request)).upper()[:3]
    currencies = sorted({e.currency.upper() for e in expenses} | {target})
    one = None
    settle_in_one = request.GET.get("settle") == "1"
    if expenses and currencies != [target]:
        one = in_one_currency(expenses, target, rates_for(trip, currencies, [e.spent_on for e in expenses]))
    lodging_estimate = {}
    for stay in trip.lodging.all():
        if stay.nightly_rate:
            lodging_estimate[stay.currency] = lodging_estimate.get(stay.currency, 0) + stay.nightly_rate * stay.nights
    summary = summarize(one["rows"], everyone) if (one and settle_in_one) else summarize(expenses, everyone)
    return render(request, "trips/trip_budget.html", {
        "trip": trip, "expenses": expenses, "summary": summary, "form": form,
        "target": target, "currencies": currencies, "one": one, "settle_in_one": settle_in_one and one,
        "can_edit": can_edit, "everyone": everyone, "lodging_estimate": sorted(lodging_estimate.items()),
        "own_rates": own_rates, "rate_formset": rate_formset,
    })


@login_required
@require_POST
def trip_rates(request, pk):
    """Save the trip's own exchange rates from the Budget page (editors). Errors show on the
    Budget page with the rows as typed."""
    from .forms import TripRateFormSet
    trip = _readable_trip(request, pk, "edit")
    formset = TripRateFormSet(request.POST, instance=trip, prefix="rates", form_kwargs={"trip": trip})
    if formset.is_valid():
        formset.save()
        messages.success(request, "Saved your own rates.")
        return redirect(reverse("trips:trip_budget", args=[trip.pk]) + "#rates")
    request.method = "GET"  # show the budget page, not the add-a-cost form's POST handling
    return trip_budget(request, pk, rate_formset=formset)


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
    legs = list(trip.transport.filter(counts_q(), origin_city__isnull=False, destination_city__isnull=False)
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
    for stay in trip.lodging.filter(counts_q()).select_related("city").order_by("check_in"):  # what counts (P4)
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
    from .ideas import map_features
    features += map_features(trip)  # the Ideas layer (P6): faint pins, off by default
    from .options import map_features as choice_features
    features += choice_features(trip)  # the Choices layer (typed-choices T3): faint pins, off by default
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
    own_cities = list(trip.cities.all())
    catalogue = list(City.objects.filter(approval_status=ApprovalStatus.APPROVED))
    origin_city = match_city(data["origin"], own_cities) or match_city(data["origin"], catalogue)
    destination_city = match_city(data["destination"], own_cities) or match_city(data["destination"], catalogue)
    last = trip.transport.filter(date=day.date).aggregate(m=Max("order"))["m"]
    from . import currencies
    leg = TransportLeg.objects.create(
        currency=currencies.default_for(trip, [getattr(origin_city, "pk", None), getattr(destination_city, "pk", None)]),
        trip=trip, date=day.date, section=section, mode=data["mode"], origin=data["origin"],
        destination=data["destination"], origin_city=origin_city, destination_city=destination_city,
        # Each end's zone from its matched city (E5), so adding times later needs no zones typed.
        origin_timezone=getattr(origin_city, "timezone", "") or "",
        destination_timezone=getattr(destination_city, "timezone", "") or "",
        est_duration=data["est_duration"], notes=data["notes"], order=(last or 0) + 1)
    trip_cities.sync(trip)
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
        context["open_tasks"] = list(activity.booking_tasks.filter(done=False))
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


# ---- "choose one" groups and votes (day-first plan, P4) ----------------------------------------
def _option_of(request, pk, option_pk, action):
    from .models import Option
    trip = _readable_trip(request, pk, action)
    option = get_object_or_404(Option.objects.filter(group__trip=trip).select_related("group__day"), pk=option_pk)
    return trip, option


@login_required
@require_POST
def option_vote(request, pk, option_pk):
    """👍 an option, or take it back (anyone who may comment). 204 for a background ``fetch``."""
    from django.http import HttpResponse
    from .models import Vote
    trip, option = _option_of(request, pk, option_pk, "comment")
    vote, made = Vote.objects.get_or_create(user=request.user, option=option)
    if not made:
        vote.delete()
    if request.headers.get("X-Requested-With") == "fetch":
        return HttpResponse(status=204)
    return redirect(_back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#group-{option.group_id}"))


@login_required
@require_POST
def option_pick(request, pk, option_pk):
    """Pick an option (editors): its items count as the day's; the others are kept as Considered. On a typed
    choice (typed-choices T2) the option becomes its real stay, meal, activity or journey, inside the option
    (``options.make_for``; picking it again reuses that item), and the trip page opens it in the panel
    (``?item=``) to add the address and confirmation — as JSON (``{"url", "anchor"}``) for a ``fetch``."""
    from django.http import JsonResponse
    from . import options as option_groups
    trip, option = _option_of(request, pk, option_pk, "edit")
    with transaction.atomic():
        option.group.pick(option, request.user)
        made = option_groups.make_for(option.group)
    if made:
        item = made[0]
        anchor = itinerary.anchor(item)
        messages.success(request, f"Picked {option.title} for {option.group.prompt}: it's on Day "
                                  f"{option.group.day.day_number} now. Add its details and confirmation.")
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse({"url": _item_page(trip, item), "anchor": anchor})
        return redirect(reverse("trips:trip_detail", args=[trip.pk]) + f"?item={anchor}#{anchor}")
    messages.success(request, f"Picked {option.title} for {option.group.prompt}.")
    return redirect(_back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{option.group.day.day_number}"))


def _item_page(trip, item):
    """An item's own (edit) page."""
    if isinstance(item, TransportLeg):
        return reverse("trips:leg_edit", args=[trip.pk, item.pk])
    if isinstance(item, Lodging):
        return reverse("trips:stay_edit", args=[trip.pk, item.pk])
    if isinstance(item, Meal):
        return reverse("trips:meal_edit", args=[trip.pk, item.day_id, item.pk])
    return reverse("trips:activity_edit", args=[trip.pk, item.day_id, item.pk])


@login_required
@require_POST
def group_reopen(request, pk, group_pk):
    """Undecide a group (editors): its options are open again, nothing is deleted."""
    from .models import OptionGroup
    trip = _readable_trip(request, pk, "edit")
    group = get_object_or_404(OptionGroup.objects.filter(trip=trip), pk=group_pk)
    group.reopen()
    messages.success(request, f"{group.prompt} is undecided again.")
    return redirect(_back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#group-{group.pk}"))


@login_required
def group_edit(request, pk, group_pk=None, day_pk=None):
    """A "choose one" group's own page (editors): what's being decided, when, and its options; each
    option lists the items in it (added to an option from the item's own page, "In option")."""
    from .forms import OptionFormSet, OptionGroupForm
    from .models import OptionGroup
    trip = _readable_trip(request, pk, "edit")
    if group_pk is not None:
        group = get_object_or_404(OptionGroup.objects.filter(trip=trip).select_related("day"), pk=group_pk)
        day = group.day
    else:
        day = get_object_or_404(trip.days.all(), pk=day_pk)
        from .quick_add import CHOICE_KINDS, choice_kind
        prompt = request.GET.get("prompt", "")[:200]
        guess = choice_kind(prompt) if prompt else {}
        if request.GET.get("kind") in CHOICE_KINDS:
            guess = {"kind": request.GET["kind"]}
        group = OptionGroup(trip=trip, day=day, prompt=prompt, order=day.option_groups.count(), **guess)
    form = OptionGroupForm(request.POST or None, instance=group)
    # The options ask for what the choice's kind needs (typed-choices T1): the kind posted, else saved.
    kind = request.POST.get("kind") if request.method == "POST" and request.POST.get("kind") else group.kind
    formset = OptionFormSet(request.POST or None, instance=group, prefix="options",
                            form_kwargs={"trip": trip, "city_ids": [day.city_id], "kind": kind})
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        kind_changed = group.pk is not None and form.initial.get("kind") != form.cleaned_data["kind"]
        with transaction.atomic():
            group = form.save()
            formset.instance = group
            formset.save()
        messages.success(request, f"Saved {group.prompt}.")
        if group_pk is None or kind_changed:  # stay on its page: options (now asking for the kind's fields) come next
            return redirect(reverse("trips:group_edit", args=[trip.pk, group.pk]) + "?next=" + quote(back))
        return redirect(back)
    from .forms import share_choices
    share_choices(formset)  # the catalogue pickers load once for every option row
    options = []
    if group.pk:
        options = list(group.options.prefetch_related("legs", "stays", "activities", "meals", "sections"))
    return render(request, "trips/group_form.html", {
        "trip": trip, "day": day, "group": group, "form": form, "formset": formset, "next": back,
        "options": options})


@login_required
def group_split(request, pk, group_pk):
    """Split a "choose one" between the day's travellers (editors; day-first plan P5): each person on
    one option; every option someone takes counts, as a track of the day. Also changes a split."""
    from .forms import SplitForm
    from .models import OptionGroup
    trip = _readable_trip(request, pk, "edit")
    group = get_object_or_404(OptionGroup.objects.filter(trip=trip).select_related("day")
                              .prefetch_related("options__travelers"), pk=group_pk)
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#group-{group.pk}")
    travelers = list(group.day.roster.order_by("name"))
    form = SplitForm(request.POST or None, group=group, travelers=travelers)
    if request.method == "POST" and form.is_valid():
        from . import options as option_groups
        with transaction.atomic():
            group.split(form.tracks(), request.user)
            option_groups.make_for(group)  # a typed choice: each taken option's item, on its track (T2)
        messages.success(request, f"Split {group.prompt}: " + "; ".join(
            f"{', '.join(t.name for t in people)} → {option.title}" for option, people in form.tracks().items()) + ".")
        return redirect(back)
    return render(request, "trips/group_split.html", {"trip": trip, "group": group, "day": group.day, "form": form,
                                                      "next": back})


@login_required
def group_delete(request, pk, group_pk):
    """Delete a group and its options (editors). Items in its options stay, as plain items on the day."""
    from .models import OptionGroup
    trip = _readable_trip(request, pk, "edit")
    group = get_object_or_404(OptionGroup.objects.filter(trip=trip).select_related("day"), pk=group_pk)
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{group.day.day_number}")
    if request.method == "POST":
        prompt = group.prompt
        group.delete()
        messages.success(request, f"Deleted {prompt}. Anything that was in its options is now simply on the day.")
        return redirect(back)
    return render(request, "trips/group_confirm_delete.html", {"trip": trip, "group": group, "next": back})


# ---- + Add: one line on a day (day-first plan, P3) --------------------------------------------
def _make_on_day(trip, day, found):
    """Make the item ``quick_add.parse`` found (``found``) on ``day``; returns (item, its page, its anchor
    on the trip page, a label). Shared by + Add (P3) and putting an idea on a day (P6)."""
    from datetime import timedelta
    from django.db.models import Max
    from apps.approval_system.models import ApprovalStatus
    from apps.locations.models import City
    from . import currencies
    from .logistics import match_city

    def next_order(queryset):
        return (queryset.aggregate(m=Max("order"))["m"] or 0) + 1

    if found["kind"] == "travel":
        own = list(trip.cities.all())
        catalogue = list(City.objects.filter(approval_status=ApprovalStatus.APPROVED))
        origin = found["origin"] or (day.city.name if day.city_id else "")
        origin_city = (match_city(origin, own) or match_city(origin, catalogue)) if origin else None
        destination_city = ((match_city(found["destination"], own) or match_city(found["destination"], catalogue))
                            if found["destination"] else None)
        item = TransportLeg.objects.create(
            trip=trip, date=day.date, mode=found["mode"], origin=origin[:120], destination=found["destination"][:120],
            origin_city=origin_city, destination_city=destination_city,
            origin_timezone=getattr(origin_city, "timezone", "") or "",
            destination_timezone=getattr(destination_city, "timezone", "") or "",
            est_duration=found["duration"], notes=found["notes"],
            currency=currencies.default_for(trip, [getattr(origin_city, "pk", None), getattr(destination_city, "pk", None)]),
            order=next_order(trip.transport.filter(date=day.date)))
        url, anchor = reverse("trips:leg_edit", args=[trip.pk, item.pk]), f"leg-{item.pk}"
        label = f"{item.origin} → {item.destination}".strip()
    elif found["kind"] == "stay":
        item = Lodging.objects.create(
            trip=trip, name=found["name"][:200], check_in=day.date, check_out=day.date + timedelta(days=found["nights"]),
            city=day.city, currency=currencies.default_for(trip, [day.city_id]))
        item.fill_day_cities()
        url, anchor, label = reverse("trips:stay_edit", args=[trip.pk, item.pk]), f"stay-{item.pk}", item.name
    elif found["kind"] == "eat":
        item = Meal.objects.create(day=day, name=found["name"][:200], meal_type=found["meal_type"],
                                   reserved_time=found["time"], order=next_order(day.meals.all()))
        url, anchor, label = reverse("trips:meal_edit", args=[trip.pk, day.pk, item.pk]), f"meal-{item.pk}", item.name
    elif found["kind"] == "do":
        item = TripActivity.objects.create(
            trip=trip, day=day, title=found["title"][:200], kind=found["activity_kind"], start_time=found["time"],
            currency=currencies.default_for(trip, [day.city_id]), order=next_order(day.activities.all()))
        url, anchor = reverse("trips:activity_edit", args=[trip.pk, day.pk, item.pk]), f"activity-{item.pk}"
        label = item.title
    else:
        item = Section.objects.create(day=day, section_type=Section.Type.NOTE, order=next_order(day.sections.all()),
                                      content={"tone": "", "paragraphs": [found["text"]] if found["text"] else []})
        url, anchor, label = reverse("trips:section_edit", args=[trip.pk, day.pk, item.pk]), f"section-{item.pk}", "a note"
    return item, url, anchor, label


@login_required
@require_POST
def quick_add(request, pk, day_pk):
    """Make a rough item on a day from one typed line (``apps/trips/quick_add.py``; a kind button
    forces the kind), then send the editor to its page: as JSON for the trip page's panel (``{"url",
    "anchor"}``), else a redirect to the page, which comes back to the day."""
    from django.http import JsonResponse
    from . import quick_add as parser
    trip, day = _editable_day(request, pk, day_pk)
    # JSON for the trip page's + Add; from inside the panel (?panel=1) the usual redirects.
    wants_json = request.headers.get("X-Requested-With") == "fetch" and not _is_panel(request)
    from .models import Option
    in_option = None
    if request.POST.get("option", "").isdigit():  # added straight into an option (the group's page, P4)
        in_option = get_object_or_404(Option.objects.filter(group__trip=trip, group__day=day), pk=request.POST["option"])
    text = " ".join(request.POST.get("text", "").split())[:300]
    kind = request.POST.get("kind", "")
    # Back to the day on the trip page, or to ``next`` (the day page's own + Add, P7).
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}")
    if kind == "options":  # a "choose one" on the day (P4): its page, to add the options
        from .models import OptionGroup
        # What it's about, guessed from the line (typed-choices T1); its page can change it.
        group = OptionGroup.objects.create(trip=trip, day=day, prompt=(text or "Choose one")[:200],
                                           order=day.option_groups.count(), **parser.choice_kind(text))
        url = reverse("trips:group_edit", args=[trip.pk, group.pk])
        messages.success(request, f"Added “{group.prompt}” to Day {day.day_number}: add its options.")
        if wants_json:
            return JsonResponse({"url": url, "anchor": f"group-{group.pk}"})
        return redirect(f"{url}?next={quote(back)}")
    if not text and kind not in parser.KINDS:
        if wants_json:
            return JsonResponse({"error": "Type what to add, or pick a kind."}, status=400)
        messages.error(request, "Type what to add, or pick a kind.")
        return redirect(back)
    found = parser.parse(text, kind=kind or None)
    item, url, anchor, label = _make_on_day(trip, day, found)
    if in_option is not None:
        item.option = in_option
        item.save(update_fields=["option"])
    trip_cities.sync(trip)
    messages.success(request, f"Added {label or 'it'} to {in_option.title if in_option else f'Day {day.day_number}'}.")
    if wants_json:
        return JsonResponse({"url": url, "anchor": anchor})
    if in_option is not None:
        return redirect(_back(request, f"{url}?next={quote(back)}"))
    return redirect(f"{url}?next={quote(back)}")


# ---- a meal on its own page (day-first plan P2: the item panel opens it) ---------------------
@login_required
def meal_edit(request, pk, day_pk, meal_pk):
    """One meal on its own page (editors): its details, confirmations and contacts & info. Meals
    are still also edited together in the day page's Meals form."""
    from .forms import MealPageForm
    trip, day = _editable_day(request, pk, day_pk)
    meal = get_object_or_404(Meal.objects.filter(day=day), pk=meal_pk)
    form = MealPageForm(request.POST or None, instance=meal, trip=trip)
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#meal-{meal.pk}")
    if request.method == "POST" and form.is_valid():
        meal = form.save()
        trip_cities.sync(trip)
        messages.success(request, f"Saved {meal.name}.")
        return redirect(back)
    from . import catalogue_links
    catalogue_links.attach_suggestions(trip, [meal], [])  # "Looks like the catalogue place …" (offered, never linked)
    return render(request, "trips/meal_form.html", {
        "trip": trip, "day": day, "meal": meal, "form": form, "next": back,
        **_item_confirmations_context(request, trip, "meal", meal),
        **_item_links_context(trip, "meal", meal),
    })


@login_required
def meal_delete(request, pk, day_pk, meal_pk):
    trip, day = _editable_day(request, pk, day_pk)
    meal = get_object_or_404(Meal.objects.filter(day=day), pk=meal_pk)
    back = _back(request, reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}")
    if request.method == "POST":
        name = meal.name
        meal.delete()
        messages.success(request, f"Deleted {name}. Its confirmations are kept.")
        return redirect(back)
    return render(request, "trips/meal_confirm_delete.html", {"trip": trip, "day": day, "meal": meal, "next": back})


# ---- catalogue notes on a trip (catalogue-notes plan, N2) -------------------------------------
@login_required
@require_POST
def trip_note_hide(request, pk, note_pk):
    """"Not for this trip" (editors): hide a catalogue note on this trip's page and booklet, or show it
    again (``show=1``). The note stays in the catalogue and on other trips."""
    from apps.catalogue_notes.models import CatalogueNote
    from .models import TripHiddenNote
    trip = _readable_trip(request, pk, "edit")
    note = get_object_or_404(CatalogueNote, pk=note_pk)
    if request.POST.get("show"):
        TripHiddenNote.objects.filter(trip=trip, note=note).delete()
        messages.success(request, "That note shows on this trip again.")
    else:
        TripHiddenNote.objects.get_or_create(trip=trip, note=note)
        messages.success(request, "Hidden on this trip. It's still in the catalogue.")
    return redirect(_back(request, reverse("trips:trip_detail", args=[trip.pk])))


# ---- stays, added and edited from their day (edit-by-day plan, E1) ----------------------------
def _stay_back(trip, stay):
    """A stay's page returns to its check-in day's "On this day", else to it on the trip page."""
    day = trip.days.filter(date=stay.check_in).first()
    if day is not None:
        return reverse("trips:day_edit", args=[trip.pk, day.pk]) + "#on-this-day"
    return reverse("trips:trip_detail", args=[trip.pk]) + "#not-on-any-day"


def _stay_from_option(trip, option_pk):
    """A new stay's starting values from a decision's option (``?from_option=<pk>``, U6): name from
    its title, notes from its detail and link. Nothing is saved until the editor saves the page."""
    from .models import TaskOption
    option = TaskOption.objects.filter(task__trip=trip, pk=option_pk).first() if option_pk.isdigit() else None
    if option is None:
        return {}
    notes = "\n".join(part for part in (option.detail, option.url) if part)
    return {"name": option.title[:200], "notes": notes, "currency": option.currency or "USD"}


def _days_filled_message(request, form):
    if form.days_filled:
        messages.info(request, f"Filled in the city for {form.days_filled} day{'s' if form.days_filled != 1 else ''} "
                               "from this stay; change any day trips by hand.")


@login_required
def stay_new(request, pk, day_pk):
    """Add a stay from its check-in day (editors): check-in is that day, check-out the next by
    default. Once saved it lands on its own page, so the confirmation and the hotel's phone can be
    added at once, like an activity's."""
    from datetime import timedelta
    from .forms import LodgingForm
    trip, day = _editable_day(request, pk, day_pk)
    initial = {"check_in": day.date, "check_out": day.date + timedelta(days=1) if day.date else None,
               "city": day.city_id, **_stay_from_option(trip, request.GET.get("from_option", ""))}
    form = LodgingForm(request.POST or None, instance=Lodging(trip=trip), initial=initial)
    back = _back(request, reverse("trips:day_edit", args=[trip.pk, day.pk]) + "#on-this-day")
    if request.method == "POST" and form.is_valid():
        stay = form.save()
        messages.success(request, f"Added {stay.name}.")
        _days_filled_message(request, form)
        return redirect(reverse("trips:stay_edit", args=[trip.pk, stay.pk]) + "?next=" + quote(back))
    return render(request, "trips/stay_form.html", {"trip": trip, "day": day, "stay": None, "form": form, "next": back})


@login_required
def stay_edit(request, pk, stay_pk):
    """One stay on its own page (editors): its details, the pin, its confirmations and its
    contacts & info. Reached from its day's "On this day" and its card on the trip page."""
    from .forms import LodgingForm
    trip = _readable_trip(request, pk, "edit")
    stay = get_object_or_404(trip.lodging.all(), pk=stay_pk)
    form = LodgingForm(request.POST or None, instance=stay)
    if request.method == "POST" and form.is_valid():
        stay = form.save()
        messages.success(request, f"Saved {stay.name}.")
        _days_filled_message(request, form)
        return redirect(_back(request, _stay_back(trip, stay)))
    return render(request, "trips/stay_form.html", {
        "trip": trip, "day": trip.days.filter(date=stay.check_in).first(), "stay": stay, "form": form,
        "next": _back(request, _stay_back(trip, stay)),
        **_item_confirmations_context(request, trip, "stay", stay),
        **_item_links_context(trip, "stay", stay),
        "open_tasks": list(stay.booking_tasks.filter(done=False)),
    })


@login_required
def stay_delete(request, pk, stay_pk):
    trip = _readable_trip(request, pk, "edit")
    stay = get_object_or_404(trip.lodging.all(), pk=stay_pk)
    back = _back(request, _stay_back(trip, stay))
    if request.method == "POST":
        name = stay.name
        stay.delete()
        messages.success(request, f"Deleted {name}. Its confirmations are kept.")
        return redirect(back)
    return render(request, "trips/stay_confirm_delete.html", {"trip": trip, "stay": stay, "next": back})


# ---- converting old sections to the day-first kinds (day-first plan, P3) -----------------------
@login_required
def trip_convert(request, pk):
    """Review turning this trip's open decision to-dos into "choose one" groups (editors; linked from the
    Needs attention banner while any is left; P4). Everything starts ticked; nothing changes until the
    ticked ones are converted, in one transaction (``apps/trips/day_first.py``)."""
    from . import day_first
    trip = _readable_trip(request, pk, "edit")
    if request.method == "POST":
        keys = [value for value in request.POST.getlist("item") if value.startswith("task-")]
        count = day_first.apply(trip, keys) if keys else 0
        if count:
            messages.success(request, f"Converted {count} item{'s' if count != 1 else ''}.")
        else:
            messages.info(request, "Nothing was ticked, so nothing changed.")
        return redirect("trips:trip_convert", pk=trip.pk)
    groups = day_first.plan(trip)
    return render(request, "trips/trip_convert.html", {
        "trip": trip, "groups": groups, "count": sum(len(items) for _day, items in groups)})


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
        applied, skipped = tidying.apply(trip, found, chosen, request.user)
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
# ---- the trip's to-dos (edit-by-day plan, E2) -----------------------------------------------
def _todo_url(trip):
    return reverse("trips:trip_todo", args=[trip.pk])


@login_required
def trip_todo(request, pk):
    """What's left to do on the trip (anyone who can see it), in order (day-first plan P7): undecided
    "choose one" groups, then what isn't booked yet, then the hand-written to-dos — open ones by
    priority and due date, the done ones folded away. Editors add, edit and tick off to-dos here; the
    rest open on the trip page."""
    from django.db.models import prefetch_related_objects
    from . import booking_tasks
    trip = _readable_trip(request, pk, "view")
    can_edit = trip.can(request.user, "edit")
    prefetch_related_objects([trip], Prefetch("booking_tasks", queryset=BookingTask.objects.select_related(
        "day").prefetch_related("options")), "days")
    booking_tasks.attach(trip)  # item / item_day / item_info; "Looks like" suggestions stay on the trip page
    tasks = sorted(trip.booking_tasks.all(),
                   key=lambda t: (t.priority, t.due is None, t.due or date.max, t.order, t.pk))
    from .models import OptionGroup
    open_groups = (OptionGroup.objects.filter(trip=trip, state=OptionGroup.State.OPEN)
                   .select_related("day").prefetch_related("options").order_by("day__date", "start_time", "order"))
    # Not booked yet (P7), worked out as on the trip page: only what counts, with its confirmations.
    page_trip = get_object_or_404(_trip_page_queryset(request.user), pk=trip.pk)
    not_booked = _trip_page_context(request, page_trip)["not_booked"]
    return render(request, "trips/trip_todo.html", {
        "trip": trip, "can_edit": can_edit, "open_groups": open_groups, "not_booked": not_booked,
        "open_tasks": [t for t in tasks if not t.done], "done_tasks": [t for t in tasks if t.done],
    })


@login_required
def task_edit(request, pk, task_pk=None):
    """Add or edit one to-do (editors). ``?leg=`` / ``?stay=`` / ``?activity=`` pre-pick what a new
    one is about (from that item's page); the pickers only offer this trip's own things."""
    from .forms import BookingTaskForm
    trip = _readable_trip(request, pk, "edit")
    task = get_object_or_404(trip.booking_tasks.all(), pk=task_pk) if task_pk is not None else None
    initial = {name: request.GET[name] for name in ("leg", "stay", "activity", "day")
               if task is None and request.GET.get(name, "").isdigit()}
    note = _note_for_todo(request) if task is None else None
    if note is not None:  # "Add as a to-do" from a catalogue note's lead time (catalogue-notes N3)
        initial.update({"title": f"Book ahead: {note.target_name}", "kind": BookingTask.Kind.BOOK,
                        "priority": BookingTask.Priority.HIGH,
                        "notes": "\n".join(part for part in (note.booking_url, note.text) if part)})
        try:
            initial["due"] = date.fromisoformat(request.GET.get("due", ""))
        except ValueError:
            pass
    form = BookingTaskForm(request.POST or None, instance=task or BookingTask(trip=trip), initial=initial, trip=trip)
    back = _back(request, _todo_url(trip))
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        if note is not None and note.pk not in saved.note_ids():
            # Remembered on a hidden line, so the note's "Book by" warning goes quiet on the trip page.
            saved.notes = (saved.notes.rstrip() + f"\n{BookingTask.FROM_NOTE}{note.pk}").strip()
            saved.save(update_fields=["notes"])
        messages.success(request, f"{'Saved' if task else 'Added'} “{saved.title}”.")
        return redirect(back)
    return render(request, "trips/task_form.html", {"trip": trip, "task": task, "form": form, "next": back,
                                                    "from_note": note})


def _note_for_todo(request):
    """The approved catalogue note a new to-do is being made from (``from_note``), else None."""
    from apps.approval_system.models import ApprovalStatus
    from apps.catalogue_notes.models import CatalogueNote
    pk = request.POST.get("from_note") or request.GET.get("from_note") or ""
    if not pk.isdigit():
        return None
    return (CatalogueNote.objects.filter(pk=pk, approval_status=ApprovalStatus.APPROVED)
            .select_related("poi", "activity", "event").first())


@login_required
def task_delete(request, pk, task_pk):
    trip = _readable_trip(request, pk, "edit")
    task = get_object_or_404(trip.booking_tasks.all(), pk=task_pk)
    back = _back(request, _todo_url(trip))
    if request.method == "POST":
        title = task.title
        task.delete()
        messages.success(request, f"Deleted “{title}”.")
        return redirect(back)
    return render(request, "trips/task_confirm_delete.html", {"trip": trip, "task": task, "next": back})


@login_required
@require_POST
def task_done(request, pk, task_pk):
    """Tick a to-do off, or back on (``done=0``), from the To do page (editors)."""
    trip = _readable_trip(request, pk, "edit")
    task = get_object_or_404(trip.booking_tasks.all(), pk=task_pk)
    task.done = request.POST.get("done", "1") != "0"
    task.save(update_fields=["done"])
    messages.success(request, f"{'Done' if task.done else 'Back on the list'}: “{task.title}”.")
    return redirect(_back(request, _todo_url(trip)))


@login_required
def task_options(request, pk, task_pk):
    """A decision's options (editors): add, edit, reorder and delete them, and choose one (or
    none). Choosing creates nothing; the trip page then offers to add it as a stay or activity."""
    from .forms import TaskOptionFormSet
    trip = _readable_trip(request, pk, "edit")
    task = get_object_or_404(trip.booking_tasks.all(), pk=task_pk)
    formset = TaskOptionFormSet(request.POST or None, instance=task, prefix="options", form_kwargs={"task": task})
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
    """Add a decision's option as a stay or an activity (U6): redirects to the new-stay or
    new-activity page of the task's day (or ``?day=``), pre-filled; a stay with no day starts on
    Day 1 (its dates are editable). Saves nothing itself."""
    from .models import TaskOption
    trip = _readable_trip(request, pk, "edit")
    option = get_object_or_404(TaskOption.objects.filter(task__trip=trip).select_related("task"), pk=option_pk)
    day_pk = request.GET.get("day") or option.task.day_id
    day = get_object_or_404(trip.days.all(), pk=day_pk) if day_pk else None
    if request.GET.get("as") == "stay":
        day = day or trip.days.order_by("day_number").first()
        if day is None:
            messages.info(request, "Add the trip's days first, then the stay on its check-in day.")
            return redirect(reverse("trips:task_options", args=[trip.pk, option.task_id]))
        back = reverse("trips:trip_detail", args=[trip.pk]) + f"#day-{day.day_number}"
        return redirect(reverse("trips:stay_new", args=[trip.pk, day.pk])
                        + f"?from_option={option.pk}&next={quote(back)}")
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
    back = _back(request, reverse("trips:trip_settings", args=[trip.pk]) + "#contacts-info")
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
    back = _back(request, reverse("trips:trip_settings", args=[trip.pk]) + "#contacts-info")
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
    back = _back(request, reverse("trips:trip_settings", args=[trip.pk]) + "#contacts-info")
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
    back = _back(request, reverse("trips:trip_settings", args=[trip.pk]) + "#loose-confirmations")
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
    back = _back(request, reverse("trips:trip_bookings", args=[trip.pk]) + "#stays-legs")
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
