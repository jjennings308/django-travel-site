"""Option groups on the trip page, the booklet and the feeds (day-first plan, P4).

**What counts.** An item (leg, stay, activity, meal, note) counts as part of the trip when it is in no
option, or in a chosen one (``counts``; ``models.counts_q`` is the same rule as a query filter, for the
calendar feed and the map). Only counted items feed the timeline, Not booked yet, Needs attention, the
cost estimate, the calendar, the map and the day's summary line: ``attach`` takes the others out of the
trip page's prefetched lists, so every later step (``itinerary``, ``booking_tasks``, ``budget``) sees
the counted ones only, with no change of its own.

``attach(trip, days, viewer)`` loads the trip's groups in three queries (groups, options, votes with
their people) and gives:

* each option ``items`` (its legs, stays, activities, meals and notes), ``vote_count``, ``voters``,
  ``voted`` (the viewer's 👍), ``cost`` (option + items, in the trip's home currency where rates allow)
  and ``duration``;
* each day ``open_groups`` (undecided, shown as boxes; the timed ones join the timeline) and
  ``picked_groups``; an open group adds one to the day's ⚠ (``day.attention``, after ``overview``);
* each item of a chosen option ``chosen_from`` (its group), so the page says "Chosen from: Afternoon".

Returns the open groups, for the Needs attention banner ("N decisions").
"""
from datetime import datetime, timedelta

from .models import OptionGroup

KINDS = ("legs", "stays", "activities", "meals", "sections")


def counts(item, options):
    """The rule for one item; ``options`` maps option id → ``Option``."""
    if not item.option_id:
        return True
    option = options.get(item.option_id)
    return option is None or option.chosen


def load(trip):
    """The trip's groups with their options and votes (and who voted): three queries."""
    from django.db.models import Prefetch
    from .models import Vote
    return list(OptionGroup.objects.filter(trip=trip)
                .prefetch_related("options", Prefetch("options__votes", queryset=Vote.objects.select_related("user"))))


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
    """Each option's estimated cost: its own estimate, its activities' and its legs' costs — in their
    currency when they share one, else in the trip's home currency (``budget``'s rates, loaded once when
    some option mixes currencies; an option with a cost there's no rate for shows none)."""
    from .budget import _cents, _money, rates_for
    home = (trip.home_currency or "USD").upper()
    wanted = []
    for group in groups:
        for option in group.options.all():
            parts = [(option.est_cost, option.currency)]
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
    groups = load(trip) if groups is None else groups
    options = {}
    for group in groups:
        for option in group.options.all():
            option.group_ref = group
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

    file(_keep(trip, "transport", keep), "legs")
    file(_keep(trip, "lodging", keep), "stays")
    for day in days:
        for attr, kind in (("ordered_activities", "activities"), ("ordered_meals", "meals"),
                           ("ordered_sections", "sections")):
            if hasattr(day, attr):
                kept, out = _split_list(getattr(day, attr), keep)
                setattr(day, attr, kept)
                file(out, kind)
    # Items of a chosen option say where they came from.
    for item in [*trip.transport.all(), *trip.lodging.all(),
                 *(i for day in days for attr in ("ordered_activities", "ordered_meals", "ordered_sections")
                   for i in getattr(day, attr, []))]:
        if item.option_id and item.option_id in options:
            item.chosen_from = options[item.option_id].group_ref
    _costs(trip, groups)
    for option in options.values():
        option.duration = _duration(option)
    by_day = {}
    for group in groups:
        group.option_list = list(group.options.all())
        group.chosen = next((o for o in group.option_list if o.chosen), None)
        group.considered = [o for o in group.option_list if not o.chosen]
        by_day.setdefault(group.day_id, []).append(group)
    for day in days:
        mine = by_day.get(day.pk, [])
        day.open_groups = [g for g in mine if g.is_open]
        day.picked_groups = [g for g in mine if not g.is_open]
    return [g for g in groups if g.is_open]


def count_on_days(days):
    """Add each day's undecided groups to its ⚠ (after ``itinerary.overview`` set it)."""
    for day in days:
        day.attention = getattr(day, "attention", 0) + len(getattr(day, "open_groups", []))
