"""The Budget page's Plan (budget-estimates B2–B3): what the trip should cost, what's booked and what's been paid,
by category and per person, in one currency.

``plan(context, target, expenses)`` works from the trip page's context (``views._trip_page_context``: only what
counts, each item's ``confirmation_list``, the option groups), so the page's query count is fixed however many
items the trip has. Rows by category (``CATEGORIES``: Travel, Stays, Activities & tickets, Food, Other) — a costed
confirmation once over everything it covers, each other counted item with its estimate (``costs.estimate``) or "no
plan" / "no booking needed", chosen options, the daily food allowance (``allowance_row``); undecided choices as
ranges outside the totals — with planned / booked / paid / left to pay per category and overall, each row's own
paid (expenses whose For is it, B3) and each traveller's share next to what they paid. ``planned_total(context,
target)`` is About this trip's line from the same plan, so the two always agree.

What one item costs (its basis, people and nights) is ``costs``; the expense arithmetic (shares, settle-up) is
``budget``.
"""
from decimal import Decimal

from .costs import (
    _cents, _days_by, _money, day_of, estimate, kind_of, money, planned_items,
)


def planned_total(context, target):
    """About this trip's estimate (B1, then B2): the plan's total and how much of it is booked, from the trip
    page's context — the same rule as the Budget page, so the two never disagree. None when nothing has a figure.

    Returns {"total", "booked", "currency", "approx", "bookings", "estimates", "unpriced", "missing"}."""
    found = plan(context, target)
    rows = [row for category in found["categories"] for row in category["rows"]]
    if not any(row["planned"] is not None for row in rows):
        return None
    totals = found["totals"]
    return {"total": totals["planned"], "booked": totals["booked"], "currency": target.upper(),
            "approx": found["approx"], "bookings": sum(1 for r in rows if r["status"] == "booked"),
            "estimates": sum(1 for r in rows if r["planned"] is not None and r["status"] != "booked"),
            "unpriced": found["unpriced"], "missing": found["missing"]}


#: The plan's categories, in order (key, label); a group's kind and an expense's category map onto them.
CATEGORIES = (("travel", "Travel"), ("stays", "Stays"), ("activities", "Activities & tickets"), ("food", "Food"),
              ("other", "Other"))
_ITEM_CATEGORY = {"leg": "travel", "stay": "stays", "activity": "activities", "meal": "food"}
_GROUP_CATEGORY = {"travel": "travel", "stay": "stays", "do": "activities", "eat": "food", "any": "other"}
#: Where a recorded expense (``TripExpense.Category``) is paid against.
EXPENSE_CATEGORY = {"flights": "travel", "transport": "travel", "lodging": "stays", "food": "food",
                    "activities": "activities", "other": "other"}
_KIND_WORDS = {"leg": ("journey", "journeys"), "stay": ("stay", "stays"), "activity": ("activity", "activities"),
               "meal": ("meal", "meals"), "section": ("item", "items")}


def _label(item):
    from .booking_tasks import label
    kind = kind_of(item) if type(item).__name__ != "Section" else "section"
    if kind == "meal":
        return item.name
    if kind == "section":
        return item.title or "Notes"
    return label(item)


def _anchor(item):
    name = type(item).__name__
    return {"TransportLeg": "leg", "Lodging": "stay", "TripActivity": "activity", "Meal": "meal",
            "Section": "section"}.get(name, "item") + f"-{item.pk}"


class _Money:
    """Adds amounts in many currencies into ``target`` through one ``Rates`` load; an amount with no rate is
    remembered (listed on the page, never guessed)."""

    def __init__(self, trip, target, currencies):
        from .budget import rates_for
        self.target = target.upper()
        foreign = {c.upper() for c in currencies if c} - {self.target}
        self.rates = rates_for(trip, foreign | {self.target}) if foreign else None
        self.missing = []

    def convert(self, amount, currency, what="", note=True):
        """``amount`` in the target currency (a Decimal), or None with no rate (listed in ``missing`` unless
        ``note`` is off, for a figure whose total is already listed)."""
        if amount is None:
            return None
        currency = (currency or self.target).upper()
        if currency == self.target or self.rates is None:
            return Decimal(amount) if currency == self.target else None
        conversion = self.rates.convert(amount, currency, self.target)
        if conversion is None:
            if note:
                self.missing.append(f"{what} ({money(amount, currency)})" if what else money(amount, currency))
            return None
        return conversion.amount


def plan(context, target, expenses=()):
    """The Budget page's Plan (B2) from the trip page's context (``views._trip_page_context``: only what counts,
    each item's ``confirmation_list``, the option groups), in ``target``.

    Rows by category — each counted leg, stay, activity and meal with an estimate (meals only with one), a costed
    confirmation once over everything it covers ("GCH7JS · 4 journeys"), a costed loose confirmation (Other), a
    chosen or split-taken option's own cost, the daily food allowance — as dicts with ``label``, ``anchor``,
    ``day``, ``estimated``, ``booked``, ``planned`` (booked else estimated, in ``target``), ``per_person``,
    ``people``, ``status`` (no plan / estimated / booked / no booking needed) and ``line``. Undecided choices are
    rows with ``range`` and stay out of the totals. Totals per category and overall: planned, booked, paid (the
    expenses by category) and left to pay (never below zero per category); ``people`` is each traveller's share
    of the plan next to what they've paid."""
    trip = context["trip"]
    by_pk, by_date = _days_by(trip)
    items = planned_items(trip)
    confirmations = list(trip.confirmations.all())
    currencies = {(getattr(i, "currency", "") or "") for i in items} | {c.currency for c in confirmations}
    currencies |= {e.currency for e in expenses} | {getattr(trip, "food_allowance_currency", "") or ""}
    for group in context.get("option_groups", []):
        currencies |= {o.currency for o in group.options.all()}
    cash = _Money(trip, target, currencies)
    everyone = list(trip.travelers.all())
    rows = []

    def add(category, **row):
        row.setdefault("range", None)
        row.setdefault("people_names", [])
        row.setdefault("keys", [])  # what an expense's For may point at to count as paid on this row (B3)
        row.setdefault("pay", None)  # the key "Record a payment" pre-fills For with
        row.setdefault("expense_category", "other")
        row["category"] = category
        rows.append(row)
        return row

    # Bookings first: a costed confirmation is one row over every counted item it covers.
    covered = {}
    for item in items:
        for confirmation in getattr(item, "confirmation_list", None) or []:
            covered.setdefault(confirmation.pk, []).append(item)
    booked_items = set()
    for confirmation in confirmations:
        if confirmation.cost is None:
            continue
        its = covered.get(confirmation.pk, [])  # none: a loose one, or one on a day's notes → Other
        booked = cash.convert(confirmation.cost, confirmation.currency, confirmation.confirmation_number)
        names = list(confirmation.travelers.all()) or everyone
        if its:
            booked_items.update((type(i), i.pk) for i in its)
            kinds = [kind_of(i) for i in its]
            first = its[0]
            if len(its) == 1:
                label = f"{_label(first)} · {confirmation.confirmation_number}"
            else:
                same = len(set(kinds)) == 1
                words = _KIND_WORDS.get(kinds[0], ("item", "items")) if same else ("item", "items")
                label = f"{confirmation.label or confirmation.confirmation_number} · {len(its)} {words[1]}"
            category = _ITEM_CATEGORY.get(kinds[0], "other")
            day = day_of(first, by_pk, by_date)
            anchor = _anchor(first)
        else:
            label, category, day, anchor = confirmation.label or confirmation.confirmation_number, "other", None, ""
        pay = f"confirmation-{confirmation.pk}"
        add(category, label=label, anchor=anchor, day=day, estimated=None, booked=booked, planned=booked,
            keys=[pay] + [_key(i) for i in its], pay=pay,
            expense_category=_expense_category(its[0]) if its else "other", booked_amount=confirmation.cost,
            booked_currency=confirmation.currency,
            per_person=(booked / len(names)).quantize(Decimal("0.01")) if booked is not None and names else None,
            people=len(names), people_names=names, status="booked",
            line=f"Booked {money(confirmation.cost, confirmation.currency)} · {confirmation.confirmation_number}")

    # Each counted item that isn't booked.
    for item in items:
        if (type(item), item.pk) in booked_items:
            continue
        kind = kind_of(item)
        cost = estimate(item, day_of(item, by_pk, by_date), trip)
        if cost is None:
            if kind == "meal":
                continue  # a meal without an estimate isn't a budget line (the allowance covers it)
            status = "no booking needed" if getattr(item, "no_booking", False) else "no plan"
            add(_ITEM_CATEGORY[kind], label=_label(item), anchor=_anchor(item), day=day_of(item, by_pk, by_date),
                estimated=None, booked=None, planned=None, per_person=None, people=0, status=status, line="",
                keys=[_key(item)])
            continue
        estimated = cash.convert(cost.total, cost.currency, _label(item)) if cost.total is not None else None
        day = day_of(item, by_pk, by_date)
        names = _names_for(item, day, trip, cost)
        add(_ITEM_CATEGORY[kind], label=_label(item), anchor=_anchor(item), day=day, estimated=estimated,
            booked=None, planned=estimated, keys=[_key(item)], people=cost.people if cost.people_known else 0, people_names=names,
            per_person=cash.convert(cost.per_person, cost.currency, note=False) if cost.per_person is not None else None,
            status="no booking needed" if getattr(item, "no_booking", False) else "estimated", line=cost.line)

    # Choices: a chosen / split-taken option's own cost counts; an undecided one is a range, outside the totals.
    for group in context.get("option_groups", []):
        category = _GROUP_CATEGORY.get(group.kind, "other")
        day = by_pk.get(group.day_id)
        if group.is_open:
            totals = [cash.convert(o.cost["total"], o.cost["currency"]) for o in group.options.all()
                      if getattr(o, "cost", None)]
            totals = [t for t in totals if t is not None]
            if totals:
                add(category, label=f"Undecided: {group.prompt}", anchor=f"group-{group.pk}", day=day,
                    estimated=None, booked=None, planned=None, per_person=None, people=0, status="undecided",
                    line="", range=(min(totals), max(totals)))
            continue
        for option in ([group.chosen] if getattr(group, "chosen", None) else []) + list(getattr(group, "tracks", [])):
            cost = option.cost_estimate()
            if cost is None or cost.total is None:
                continue
            total = Decimal(option.own_cost)
            estimated = cash.convert(total, cost.currency, option.title)
            names = list(option.travelers.all()) or (list(day.roster) if day is not None else everyone)
            add(category, label=f"{group.prompt}: {option.title}", anchor=f"group-{group.pk}", day=day,
                estimated=estimated, booked=None, planned=estimated, people=len(names), people_names=names,
                per_person=(estimated / len(names)).quantize(Decimal("0.01")) if estimated is not None and names
                else None, status="estimated", line=cost.line)

    # The daily food allowance, for the food no meal prices.
    allowance = allowance_row(trip, context["days"], cash)
    if allowance is not None:
        add("food", **allowance)

    return _totals(rows, expenses, cash, everyone, target)


def _key(item):
    """An item's key as an expense's For names it: ``leg-12``, ``stay-3``, ``activity-7``, ``meal-4``."""
    return f"{kind_of(item)}-{item.pk}"


def _expense_category(item):
    """The expense category a payment for ``item`` goes in (``TripExpense.Category``)."""
    kind = kind_of(item)
    if kind == "leg":
        return "flights" if item.mode == "plane" else "transport"
    return {"stay": "lodging", "activity": "activities", "meal": "food"}.get(kind, "other")


def _names_for(item, day, trip, cost):
    """Who an estimate is for, by name, when that's known: its own travellers, else the day's, else the trip's —
    unless ``cost_people`` says another number (then nobody by name)."""
    if not cost.people_known or getattr(item, "cost_people", None):
        return []
    own = getattr(item, "travelers", None)
    if own is not None and kind_of(item) == "activity" and own.all():
        return list(own.all())
    if day is not None and len(day.roster):
        return list(day.roster)
    return list(trip.travelers.all())


def allowance_row(trip, days, cash):
    """"€45 per person per day × 11 days × 6 = €2,970": ``Trip.food_allowance`` on each day not marked
    ``meals_included``, for the people on it (its roster). None when the trip has no allowance."""
    amount = getattr(trip, "food_allowance", None)
    if not amount:
        return None
    currency = (trip.food_allowance_currency or trip.home_currency or "").upper()
    counted = [day for day in days if not day.meals_included]
    heads = [len(day.roster) for day in counted]
    person_days = sum(heads)
    total = Decimal(amount) * person_days
    skipped = len(days) - len(counted)
    if heads and len(set(heads)) == 1:
        line = (f"{money(amount, currency)} per person per day × {len(counted)} day{'s' if len(counted) != 1 else ''}"
                f" × {heads[0]} = {money(total, currency)}")
    else:
        line = f"{money(amount, currency)} per person per day × {person_days} person-days = {money(total, currency)}"
    if skipped:
        line += f" · {skipped} day{'s' if skipped != 1 else ''} with meals included skipped"
    estimated = cash.convert(total, currency, "Daily food")
    names = list(trip.travelers.all())
    return {"label": "Daily food allowance", "anchor": "", "day": None, "estimated": estimated, "booked": None,
            "planned": estimated, "people": len(names), "people_names": names,
            "per_person": (estimated / len(names)).quantize(Decimal("0.01")) if estimated is not None and names else None,
            "status": "estimated", "line": line}


def _totals(rows, expenses, cash, everyone, target):
    """Categories with their rows and totals, the overall totals and each traveller's share against what they paid."""
    zero = Decimal("0.00")
    categories = []
    paid_by_category = {key: zero for key, _ in CATEGORIES}
    paid_by_person = {person.pk: zero for person in everyone}
    for expense in expenses:
        amount = cash.convert(expense.amount, expense.currency, expense.description)
        if amount is None:
            continue
        paid_by_category[EXPENSE_CATEGORY.get(expense.category, "other")] += amount
        if expense.paid_by_id in paid_by_person:
            paid_by_person[expense.paid_by_id] += amount
    # Paid per row (B3): an expense whose For is the row's booking or one of its items.
    from django.contrib.contenttypes.models import ContentType
    kinds = {ct.pk: name for name, ct in (
        (name, ContentType.objects.get_by_natural_key("trips", model))
        for name, model in (("leg", "transportleg"), ("stay", "lodging"), ("activity", "tripactivity"),
                            ("meal", "meal"), ("confirmation", "confirmation")))}
    paid_for = {}
    for expense in expenses:
        if expense.for_type_id in kinds and expense.for_id:
            amount = cash.convert(expense.amount, expense.currency, note=False)
            if amount is not None:
                key = f"{kinds[expense.for_type_id]}-{expense.for_id}"
                paid_for[key] = paid_for.get(key, zero) + amount
    for row in rows:
        row["paid"] = sum((paid_for.get(key, zero) for key in row["keys"]), zero)
    share = {person.pk: zero for person in everyone}
    unassigned = zero
    for row in rows:
        planned = row["planned"]
        if planned is None or row["range"]:
            continue
        names = [p for p in row["people_names"] if p.pk in share]
        if names:
            base, extra = divmod(_cents(planned), len(names))
            for i, person in enumerate(sorted(names, key=lambda p: (p.name, p.pk))):
                share[person.pk] += _money(base + (1 if i < extra else 0))
        else:
            unassigned += planned
    overall = {"planned": zero, "booked": zero, "paid": zero, "left": zero}
    for key, name in CATEGORIES:
        mine = sorted((r for r in rows if r["category"] == key),
                      key=lambda r: (r["day"].date if r["day"] is not None and r["day"].date else date_max(), r["label"]))
        planned = sum((r["planned"] for r in mine if r["planned"] is not None and not r["range"]), zero)
        booked = sum((r["booked"] for r in mine if r["booked"] is not None), zero)
        paid = paid_by_category[key]
        left = max(planned - paid, zero)
        if not mine and not paid:
            continue
        categories.append({"key": key, "name": name, "rows": mine, "planned": planned, "booked": booked,
                           "paid": paid, "left": left})
        for field, value in (("planned", planned), ("booked", booked), ("paid", paid), ("left", left)):
            overall[field] += value
    people = [{"person": p, "share": share[p.pk], "paid": paid_by_person[p.pk]} for p in everyone]
    unpriced = sum(1 for r in rows if r["status"] in ("estimated", "no booking needed") and r["line"]
                   and r["planned"] is None and not r["range"])
    return {"target": target, "categories": categories, "totals": overall, "people": people,
            "unassigned": unassigned, "missing": cash.missing, "approx": cash.rates is not None, "unpriced": unpriced}


def date_max():
    from datetime import date
    return date.max
