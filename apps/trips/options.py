"""Option groups on the trip page, the booklet and the feeds (day-first plan, P4).

**What counts.** An item (leg, stay, activity, meal, note) counts as part of the trip when it is in no
option, in a chosen one, or in an option someone takes in a split group (P5) (``counts``; ``models.counts_q`` is the same rule as a query filter, for the
calendar feed and the map). Only counted items feed the timeline, Not booked yet, Needs attention, the
cost estimate, the calendar, the map and the day's summary line: ``attach`` takes the others out of the
trip page's prefetched lists, so every later step (``itinerary``, ``booking_tasks``, ``budget``) sees
the counted ones only, with no change of its own.

``attach(trip, days, viewer)`` loads the trip's groups in four queries (groups, options, their
travellers, votes with their people) and gives:

* each option ``items`` (its legs, stays, activities, meals and notes), ``vote_count``, ``voters``,
  ``voted`` (the viewer's 👍), ``cost`` (option + items, in the trip's home currency where rates allow)
  and ``duration``;
* each day ``open_groups`` (undecided, shown as boxes; the timed ones join the timeline) and
  ``picked_groups``; an open group adds one to the day's ⚠ (``day.attention``, after ``overview``);
* each item of a chosen option ``chosen_from`` (its group), so the page says "Chosen from: Afternoon".

**Split** (P5): a split group's options with travellers are its **tracks** (``group.tracks``; the others
are ``considered``), each with ``who`` ("Debbie, John"). Their items count — so Not booked yet, the cost
estimate and the map add every track — and carry ``track`` (the option): ``itinerary.timeline`` leaves
them out of the shared timeline and shows the group there as one entry whose tracks hold them, side by
side (``day.split_groups``). Notes in a track leave ``day.ordered_sections`` for their track. Who is on
an item (the calendar's "only mine") is ``on_it``: an activity's own travellers, else its option's
travellers in a split, else the day's.

Returns the open groups, for the Needs attention banner ("N decisions").
"""
from datetime import datetime, timedelta

from .models import OptionGroup

KINDS = ("legs", "stays", "activities", "meals", "sections")


def taken(option):
    """In a split group, someone takes this option (P5). Needs ``option.group`` and its travellers."""
    return option.group.state == OptionGroup.State.SPLIT and bool(option.travelers.all())


def counts(item, options):
    """The rule for one item; ``options`` maps option id → ``Option``."""
    if not item.option_id:
        return True
    option = options.get(item.option_id)
    return option is None or option.chosen or taken(option)


def on_it(own, option_travelers, day_travelers):
    """Who is on an item (P5): its own travellers, else its split option's, else the day's (blank =
    everyone)."""
    return list(own) or list(option_travelers) or list(day_travelers)


def load(trip):
    """The trip's groups with their options, who takes them (P5) and votes (and who voted): four queries."""
    from django.db.models import Prefetch
    from .models import Option, Vote
    # An option's catalogue link (typed-choices T1) comes with it, so its line costs no query.
    options = Option.objects.select_related("poi", "activity", "event__related_activity", "event__poi", "city")
    return list(OptionGroup.objects.filter(trip=trip)
                .prefetch_related(Prefetch("options", queryset=options), "options__travelers",
                                  Prefetch("options__votes", queryset=Vote.objects.select_related("user"))))


def _keep(owner, name, keep):
    """Narrow a prefetched relation of ``owner`` (``trip.transport.all()``) to the items ``keep`` allows."""
    cache = getattr(owner, "_prefetched_objects_cache", {}).get(name)
    if cache is not None:
        removed = [item for item in cache if not keep(item)]
        cache._result_cache = [item for item in cache if keep(item)]
        return removed
    return []


def _split_list(items, keep):
    kept = [item for item in items if keep(item)]
    return kept, [item for item in items if not keep(item)]


def _duration(option):
    total, known = timedelta(), False
    for leg in option.items["legs"]:
        if leg.departure_at and leg.arrival_at:
            total += leg.arrival_at - leg.departure_at
            known = True
        elif leg.est_duration:
            total += leg.est_duration
            known = True
    for activity in option.items["activities"]:
        if activity.start_time and activity.end_time:
            day = datetime(2000, 1, 1)
            total += datetime.combine(day, activity.end_time) - datetime.combine(day, activity.start_time)
            known = True
    if not known:
        return ""
    minutes = int(total.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    return f"~{hours} h {minutes} min" if hours and minutes else f"~{hours} h" if hours else f"~{minutes} min"


def _costs(trip, groups):
    """Each option's estimated cost: its own estimate (``Option.own_cost``: per night × nights for a stay), its
    activities' and its legs' costs — in their
    currency when they share one, else in the trip's home currency (``budget``'s rates, loaded once when
    some option mixes currencies; an option with a cost there's no rate for shows none)."""
    from .budget import _cents, _money, rates_for
    home = (trip.home_currency or "USD").upper()
    wanted = []
    for group in groups:
        for option in group.options.all():
            parts = [(option.own_cost, option.currency)]  # a stay's nightly price × its nights (T1)
            parts += [(a.est_cost, a.currency) for a in option.items["activities"]]
            parts += [(leg.cost, leg.currency) for leg in option.items["legs"]]
            wanted.append((option, [(amount, (currency or home).upper()) for amount, currency in parts
                                    if amount is not None]))
    foreign = {currency for _, parts in wanted if len({c for _, c in parts}) > 1 for _, currency in parts} - {home}
    rates = rates_for(trip, foreign | {home}) if foreign else None
    for option, parts in wanted:
        option.cost = None
        if not parts:
            continue
        own = {currency for _, currency in parts}
        if len(own) == 1:  # one currency: shown in it, nothing to convert
            option.cost = {"total": _money(sum(_cents(amount) for amount, _ in parts)), "currency": own.pop(),
                           "approx": False}
            continue
        total, approx = 0, False
        for amount, currency in parts:
            if currency != home:
                conversion = rates.convert(amount, currency, home) if rates else None
                if conversion is None:
                    option.cost = None
                    break
                amount, approx = conversion.amount, True
            total += _cents(amount)
        else:
            option.cost = {"total": _money(total), "currency": home, "approx": approx}


def attach(trip, days, viewer=None, groups=None):
    """See the module docstring. ``days`` are the trip page's days (with their prefetched lists)."""
    from .costs import people_for
    groups = load(trip) if groups is None else groups
    options = {}
    day_by_pk = {day.pk: day for day in days}
    for group in groups:
        for option in group.options.all():
            option.group_ref = group
            option.group = group  # the cached object, so taken() costs no query
            # Who its cost is for (budget-estimates B1), from the page's prefetched rosters: no query.
            option._people = people_for(option, day_by_pk.get(group.day_id), trip)
            option.items = {kind: [] for kind in KINDS}
            options[option.pk] = option
            votes = list(option.votes.all())
            option.vote_count = len(votes)
            option.voters = [vote.user.get_full_name() or vote.user.username for vote in votes]
            option.voted = viewer is not None and any(vote.user_id == viewer.pk for vote in votes)

    def keep(item):
        return counts(item, options)

    def file(items, kind):
        for item in items:
            options[item.option_id].items[kind].append(item)

    def on_track(item):
        option = options.get(item.option_id) if item.option_id else None
        return option is not None and taken(option)

    file(_keep(trip, "transport", keep), "legs")
    file(_keep(trip, "lodging", keep), "stays")
    for day in days:
        for attr, kind in (("ordered_activities", "activities"), ("ordered_meals", "meals"),
                           ("ordered_sections", "sections")):
            if hasattr(day, attr):
                kept, out = _split_list(getattr(day, attr), keep)
                if attr == "ordered_sections":  # a track's notes are read in its track (P5)
                    kept, tracked = _split_list(kept, lambda s: not on_track(s))
                    out += tracked
                setattr(day, attr, kept)
                file(out, kind)
    # Items of a chosen option say where they came from; a split's items know their track (P5).
    for item in [*trip.transport.all(), *trip.lodging.all(),
                 *(i for day in days for attr in ("ordered_activities", "ordered_meals", "ordered_sections")
                   for i in getattr(day, attr, []))]:
        if item.option_id and item.option_id in options:
            option = options[item.option_id]
            item.chosen_from = option.group_ref
            if taken(option):
                item.track = option
                option.items[_kind_of(item)].append(item)
    _costs(trip, groups)
    for option in options.values():
        option.duration = _duration(option)
    by_day = {}
    for group in groups:
        group.option_list = list(group.options.all())
        group.chosen = next((o for o in group.option_list if o.chosen), None)
        group.tracks = [o for o in group.option_list if taken(o)]
        group.considered = [o for o in group.option_list if not o.chosen and o not in group.tracks]
        for option in group.tracks:
            option.who = ", ".join(t.name for t in option.travelers.all())
        by_day.setdefault(group.day_id, []).append(group)
    for day in days:
        mine = by_day.get(day.pk, [])
        day.open_groups = [g for g in mine if g.is_open]
        day.picked_groups = [g for g in mine if g.state == OptionGroup.State.PICKED]
        day.split_groups = [g for g in mine if g.state == OptionGroup.State.SPLIT]
    return [g for g in groups if g.is_open]


def _kind_of(item):
    from .models import Lodging, Meal, TransportLeg
    return ("legs" if isinstance(item, TransportLeg) else "stays" if isinstance(item, Lodging)
            else "meals" if isinstance(item, Meal) else "activities")


def count_on_days(days):
    """Add each day's undecided groups to its ⚠ (after ``itinerary.overview`` set it)."""
    for day in days:
        day.attention = getattr(day, "attention", 0) + len(getattr(day, "open_groups", []))


# ---- a typed option becomes its item (typed-choices T2) --------------------------------------
def _city_of(option):
    """The catalogue city an option is in: its own city, else its place's, venue's or event's."""
    if option.city_id:
        return option.city
    for target in (option.poi, option.event, option.activity):
        if target is not None and getattr(target, "city_id", None):
            return target.city
    if option.activity_id and option.activity.venue_id:
        return option.activity.venue.city
    return None


def make_item(option, actor=None):
    """Copy a typed option into the real item on its choice's day (once: decision 1, no sync), saved inside
    the option so it counts exactly while the option does, and remember it in ``option.made``. Returns
    the item, or None for an "Anything" choice. ``Option.made`` set already → that item (picking again reuses
    it). Stay → a ``Lodging`` from the day for the option's nights; eat → a ``Meal`` at the choice's time;
    do → a ``TripActivity`` (start / end from the choice); travel → a planned ``TransportLeg``."""
    from django.db.models import Max
    from apps.approval_system.models import ApprovalStatus
    from apps.locations.models import City
    from . import currencies, quick_add, trip_cities
    from .logistics import match_city
    from .models import Lodging, Meal, OptionGroup, TransportLeg, TripActivity
    if option.made_id is not None:
        made = option.made
        if made is not None:
            return made
    group = option.group
    day, trip = group.day, group.trip
    Kind = OptionGroup.Kind
    city = _city_of(option)
    notes = "\n".join(p for p in (option.notes, option.url) if p)
    currency = option.currency or currencies.default_for(trip, [getattr(city, "pk", None) or day.city_id])

    def next_order(queryset):
        return (queryset.aggregate(m=Max("order"))["m"] or 0) + 1

    # What its cost means comes along (budget-estimates B1): the option's basis (its own or its kind's default,
    # written out so a meal made from a "total" option isn't read per person) and who it's for.
    from .costs import basis_of
    cost_meaning = {"cost_basis": basis_of(option) if option.est_cost is not None else "",
                    "cost_people": option.cost_people}

    if group.kind == Kind.STAY:
        if not day.date:
            return None
        nights = option.stay_nights or 1
        item = Lodging.objects.create(
            trip=trip, name=option.title[:200], address=option.place_text or (option.poi.address if option.poi_id else ""),
            city=city or day.city, check_in=day.date, check_out=day.date + timedelta(days=nights),
            nightly_rate=option.est_cost, currency=currency, notes=notes, option=option,
            rooms=option.rooms, **cost_meaning)
        item.fill_day_cities()
    elif group.kind == Kind.EAT:
        item = Meal.objects.create(
            day=day, name=option.title[:200], meal_type=group.meal_type or Meal.MealType.DINNER,
            reserved_time=group.start_time, poi=option.poi, why_recommended=notes,
            order=next_order(day.meals.all()), option=option,
            est_cost=option.est_cost, currency=currency if option.est_cost is not None else "", **cost_meaning)
    elif group.kind == Kind.DO:
        poi = option.poi or (option.event.poi if option.event_id and option.event.poi_id else None) or (
            option.activity.venue if option.activity_id and option.activity.venue_id else None)
        kind = TripActivity.Kind.TICKET if option.event_id else quick_add.parse(option.title, "do")["activity_kind"]
        item = TripActivity.objects.create(
            trip=trip, day=day, title=option.title[:200], kind=kind, poi=poi, event=option.event,
            place_text="" if poi else (option.place_text or getattr(city, "name", "")),
            start_time=group.start_time, end_time=group.end_time, est_cost=option.est_cost, currency=currency,
            notes=notes, order=next_order(day.activities.all()), option=option, **cost_meaning)
    elif group.kind == Kind.TRAVEL:
        own = list(trip.cities.all())
        catalogue = None

        def find(name):
            nonlocal catalogue
            if not name:
                return None
            found = match_city(name, own)
            if found is None:
                catalogue = catalogue if catalogue is not None else list(
                    City.objects.filter(approval_status=ApprovalStatus.APPROVED))
                found = match_city(name, catalogue)
            return found
        origin = option.from_text or (day.city.name if day.city_id else "")
        origin_city, destination_city = find(origin), find(option.to_text) or city
        item = TransportLeg.objects.create(
            trip=trip, date=day.date, mode=group.mode or TransportLeg.Mode.OTHER, origin=origin[:120],
            destination=(option.to_text or getattr(destination_city, "name", ""))[:120],
            origin_city=origin_city, destination_city=destination_city,
            origin_timezone=getattr(origin_city, "timezone", "") or "",
            destination_timezone=getattr(destination_city, "timezone", "") or "",
            cost=option.est_cost, currency=currency, notes=notes,
            order=next_order(trip.transport.filter(date=day.date)), option=option, **cost_meaning)
    else:
        return None
    from django.contrib.contenttypes.models import ContentType
    option.made_type, option.made_id = ContentType.objects.get_for_model(item), item.pk
    option.save(update_fields=["made_type", "made_id"])
    trip_cities.sync(trip)
    return item


def has_items(option):
    """Whether something was put in the option by hand ("In option"): then it has its real item already."""
    return any(getattr(option, name).exists() for name in ("legs", "stays", "activities", "meals", "sections"))


def make_for(group):
    """After a pick or a split of a typed choice (T2): the item for each option it now takes — the chosen one,
    or every option someone takes in a split — made once (``make_item`` reuses ``option.made``); an option
    with items put in it by hand makes nothing. Returns the items made or reused, in option order."""
    from .models import OptionGroup
    if group.kind == OptionGroup.Kind.ANY:
        return []
    items = []
    for option in group.options.prefetch_related("travelers"):
        taking = option.chosen or (group.state == OptionGroup.State.SPLIT and option.travelers.all())
        if not taking:
            continue
        if option.made_id is None and has_items(option):
            continue
        item = make_item(option)
        if item is not None:
            items.append(item)
    return items


def map_features(trip):
    """The trip map's **Choices** layer (typed-choices T3; off by default): a faint pin per option of an undecided
    typed choice that has a place — its catalogue place, its event's or activity's venue, else its city's centre —
    with the choice's prompt and the option's votes. One query."""
    from django.db.models import Count
    from django.urls import reverse
    from .models import Option, OptionGroup
    options = (Option.objects.filter(group__trip=trip, group__state=OptionGroup.State.OPEN)
               .exclude(group__kind=OptionGroup.Kind.ANY)
               .select_related("group__day", "poi", "city", "event__poi", "event__city", "activity__venue",
                               "activity__city")
               .annotate(votes_n=Count("votes")).order_by("group__day__day_number", "group_id", "order"))
    features = []
    for option in options:
        poi = option.poi or (option.event.poi if option.event_id and option.event.poi_id else None) or (
            option.activity.venue if option.activity_id and option.activity.venue_id else None)
        city = option.city or (option.event.city if option.event_id else None) or (
            option.activity.city if option.activity_id else None) or (poi.city if poi is not None else None)
        spot = poi if poi is not None and poi.latitude is not None else city
        if spot is None or spot.latitude is None or spot.longitude is None:
            continue
        group = option.group
        votes = f" · 👍 {option.votes_n}" if option.votes_n else ""
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(spot.longitude), float(spot.latitude)]},
            "properties": {
                "layer": "choices", "marker": "idea", "name": option.title,
                "subtitle": f"Day {group.day.day_number} · {group.prompt}: undecided{votes}",
                "url": reverse("trips:trip_detail", args=[trip.pk]) + f"#group-{group.pk}",
            },
        })
    return features
