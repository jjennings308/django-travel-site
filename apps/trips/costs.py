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

``annotate(trip)`` gives each counted item on the trip page its quiet ``cost_note`` (B3). The Budget page's Plan,
which adds these up, is ``budget_plan``; the expense arithmetic (shares, settle-up) is ``budget``.
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


# ---- costs where you plan (budget-estimates B3) --------------------------------------------------------------

def note_for(item, day, trip):
    """The quiet note at the end of an item's row on its day: "€1,140 · booked" (a costed confirmation covers it;
    "€380 for 4 · booked" when it covers more), else "≈ €190 pp" / "≈ €1,140" from its estimate, else ""."""
    for confirmation in getattr(item, "confirmation_list", None) or []:
        if confirmation.cost is not None:
            covered = len(confirmation.links.all())
            amount = money(confirmation.cost, confirmation.currency)
            return f"{amount} for {covered} · booked" if covered > 1 else f"{amount} · booked"
    cost = estimate(item, day, trip)
    if cost is None:
        return ""
    if cost.per_person is not None and cost.people > 1:
        return f"≈ {money(cost.per_person, cost.currency)} pp"
    if cost.total is not None:
        return f"≈ {money(cost.total, cost.currency)}"
    return f"≈ {money(cost.amount, cost.currency)} {Basis(cost.basis).label.lower()}"


def annotate(trip):
    """Give each counted leg, stay, activity and meal its ``cost_note`` (no queries: the trip page's prefetch)."""
    by_pk, by_date = _days_by(trip)
    for item in planned_items(trip):
        item.cost_note = note_for(item, day_of(item, by_pk, by_date), trip)
