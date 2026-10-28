"""What a cost means (budget-estimates plan, B1): every plannable item's estimate with its **basis**.

Legs, stays, trip activities, meals and choice options each have one amount (as their existing fields:
``TransportLeg.cost``, ``Lodging.nightly_rate``, ``est_cost``; read through ``amount_of``) and a currency, a
``cost_basis`` and, where it matters, ``cost_people`` (overrides the people count) and ``rooms`` (stays and
stay options). ``estimate(item, day, trip)`` works out the item's total and each person's share and says how
in one ``line``: "€95 per room per night × 3 rooms × 4 nights = €1,140 · €190 each (6)". Nothing is stored twice.

Pure (no queries) over what the trip page prefetches: an activity's and a split option's travellers, the
day's roster (``days__travelers``) and the trip's travellers. Blank ``cost_basis`` = the kind's default, which is
what the bare numbers always meant (``DEFAULT``): a leg's cost and an activity's estimate are the total, a stay's
rate and a stay option's estimate are per night, a meal's estimate is per person, other options' the total.

``plan(context, target, expenses)`` is the Budget page's Plan (B2): rows by category (Travel, Stays, Activities &
tickets, Food, Other) — per item the booked cost when a confirmation with a cost covers it (each confirmation once,
however many items it covers), else the item's estimate; chosen options; the daily food allowance; undecided
choices as ranges outside the totals — with planned / booked / paid / left to pay and each traveller's share.
``planned_total(context, target)`` is About this trip's line from the same plan, so the two always agree.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db import models


class Basis(models.TextChoices):
    TOTAL = "total", "Total"
    PER_PERSON = "person", "Per person"
    PER_NIGHT = "night", "Per night"
    PER_ROOM_NIGHT = "room_night", "Per room per night"
    PER_PERSON_NIGHT = "person_night", "Per person per night"


STAY_BASES = (Basis.PER_NIGHT, Basis.PER_ROOM_NIGHT, Basis.PER_PERSON_NIGHT, Basis.TOTAL)
#: The bases each kind offers, its default first.
BASES_FOR = {
    "leg": (Basis.TOTAL, Basis.PER_PERSON),
    "stay": STAY_BASES,
    "activity": (Basis.TOTAL, Basis.PER_PERSON),
    "meal": (Basis.PER_PERSON, Basis.TOTAL),
    "option": (Basis.TOTAL, Basis.PER_PERSON),
    "stay_option": STAY_BASES,
}
#: What a blank basis means: what the bare amount always meant.
DEFAULT = {kind: bases[0] for kind, bases in BASES_FOR.items()}

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "CHF ", "CAD": "CA$", "AUD": "A$"}


def kind_of(item):
    """leg / stay / activity / meal / option / stay_option."""
    name = type(item).__name__
    if name == "Option":
        group = getattr(item, "group", None)
        return "stay_option" if group is not None and group.kind == "stay" else "option"
    return {"TransportLeg": "leg", "Lodging": "stay", "TripActivity": "activity", "Meal": "meal"}[name]


def amount_of(item):
    """The item's amount, whatever its field is called."""
    name = type(item).__name__
    if name == "TransportLeg":
        return item.cost
    if name == "Lodging":
        return item.nightly_rate
    return item.est_cost


def basis_of(item):
    """Its basis: the one set when the kind offers it, else the kind's default."""
    kind = kind_of(item)
    basis = getattr(item, "cost_basis", "") or ""
    return basis if basis in BASES_FOR[kind] else DEFAULT[kind]


def money(amount, currency):
    """"€95", "€15.50", "$1,140", "CHF 12" — whole amounts without cents."""
    if amount is None:
        return ""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    text = f"{amount:,.0f}" if amount == amount.to_integral_value() else f"{amount:,.2f}"
    code = (currency or "").upper()
    symbol = SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{text}"
    return f"{code} {text}".strip()


def _cents(amount):
    return int((Decimal(amount) * 100).to_integral_value())


def _money(cents):
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def people_for(item, day=None, trip=None):
    """(count, known): ``cost_people`` when set, else the item's own travellers (an activity's, a split
    option's), else the day's roster, else the trip's travellers; (0, False) when none of them says."""
    override = getattr(item, "cost_people", None)
    if override:
        return override, True
    own = getattr(item, "travelers", None)
    if own is not None and kind_of(item) in ("activity", "option", "stay_option"):
        count = len(own.all())
        if count:
            return count, True
    if day is not None:
        count = len(day.roster)
        if count:
            return count, True
    if trip is not None:
        count = len(trip.travelers.all())
        if count:
            return count, True
    return 0, False


def roster_count(day=None, trip=None):
    """How many are on ``day`` (its roster, else the trip's travellers), or on the trip; 0 when unknown."""
    if day is not None:
        return len(day.roster)
    return len(trip.travelers.all()) if trip is not None else 0


def nights_for(item):
    """A stay's nights (check-out − check-in), a stay option's ``stay_nights``; None when unknown."""
    kind = kind_of(item)
    if kind == "stay":
        if item.check_in and item.check_out and item.check_out > item.check_in:
            return (item.check_out - item.check_in).days
        return None
    if kind == "stay_option":
        return item.stay_nights
    return None


@dataclass
class Cost:
    amount: Decimal
    currency: str
    basis: str
    people: int
    people_known: bool
    nights: int | None
    rooms: int | None
    total: Decimal | None
    per_person: Decimal | None
    line: str


def estimate(item, day=None, trip=None, people=None):
    """The item's ``Cost`` (None when it has no amount). ``people`` = (count, known) when already worked out."""
    amount = amount_of(item)
    if amount is None:
        return None
    currency = (item.currency or "").upper()
    basis = basis_of(item)
    count, known = people if people is not None else people_for(item, day, trip)
    nights = nights_for(item) if basis in (Basis.PER_NIGHT, Basis.PER_ROOM_NIGHT, Basis.PER_PERSON_NIGHT) else None
    rooms = getattr(item, "rooms", None) if basis == Basis.PER_ROOM_NIGHT else None
    m = lambda value: money(value, currency)  # noqa: E731
    nights_text = f"{nights} night{'s' if nights != 1 else ''}" if nights else "? nights"
    head = m(amount)
    total = None
    if basis == Basis.TOTAL:
        total, line = amount, f"{head} total"
    elif basis == Basis.PER_PERSON:
        if known:
            total = amount * count
            line = f"{head} per person × {count} = {m(total)}"
        else:
            line = f"{head} per person"
    elif basis == Basis.PER_NIGHT:
        total = amount * nights if nights else None
        line = f"{head} per night × {nights_text}" + (f" = {m(total)}" if total is not None else "")
    elif basis == Basis.PER_ROOM_NIGHT:
        rooms_text = f"{rooms} room{'s' if rooms != 1 else ''}" if rooms else "? rooms"
        total = amount * rooms * nights if rooms and nights else None
        line = f"{head} per room per night × {rooms_text} × {nights_text}" + (f" = {m(total)}" if total is not None else "")
    else:  # per person per night
        total = amount * count * nights if known and nights else None
        line = f"{head} per person per night × {count if known else '?'} × {nights_text}" + (
            f" = {m(total)}" if total is not None else "")
    per_person = None
    if total is not None and known and count:
        base, extra = divmod(_cents(total), count)
        per_person = _money(base + (1 if extra else 0))  # the remainder rides on the first share
        if basis != Basis.PER_PERSON and count > 1:
            line += f" · {m(per_person)} each ({count})"
    if not known:
        line += " · people not set"
    return Cost(amount=Decimal(amount), currency=currency, basis=basis, people=count, people_known=known,
                nights=nights, rooms=rooms, total=Decimal(total) if total is not None else None,
                per_person=per_person, line=line)


def _days_by(trip):
    days = list(trip.days.all())
    return {day.pk: day for day in days}, {day.date: day for day in days if day.date}


def day_of(item, by_pk, by_date):
    """The day an item is on (a stay: its check-in day; a leg: its placed day or its date's)."""
    kind = kind_of(item)
    if kind == "leg":
        return getattr(item, "on_day", None) or by_date.get(item.date)
    if kind == "stay":
        return by_date.get(item.check_in)
    if kind in ("activity", "meal"):
        return by_pk.get(item.day_id)
    group = getattr(item, "group", None)
    return by_pk.get(group.day_id) if group is not None else None


def planned_items(trip):
    """The items that count (the trip page has already taken out undecided options' items, P4): legs, stays,
    activities and meals, in that order."""
    meals, activities = [], []
    for day in trip.days.all():
        activities += list(getattr(day, "ordered_activities", []))
        meals += list(getattr(day, "ordered_meals", []) or [])
    return list(trip.transport.all()) + list(trip.lodging.all()) + activities + meals


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


# ---- the planned budget (budget-estimates B2) ---------------------------------------------------------------

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
        add(category, label=label, anchor=anchor, day=day, estimated=None, booked=booked, planned=booked,
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
                estimated=None, booked=None, planned=None, per_person=None, people=0, status=status, line="")
            continue
        estimated = cash.convert(cost.total, cost.currency, _label(item)) if cost.total is not None else None
        day = day_of(item, by_pk, by_date)
        names = _names_for(item, day, trip, cost)
        add(_ITEM_CATEGORY[kind], label=_label(item), anchor=_anchor(item), day=day, estimated=estimated,
            booked=None, planned=estimated, people=cost.people if cost.people_known else 0, people_names=names,
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
