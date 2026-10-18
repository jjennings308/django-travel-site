# trips/budget.py
"""Trip expense arithmetic: equal splits, balances and who-owes-whom.

Everything works in cents (integers), per currency, so nothing is lost to
floating point and the totals always balance: a cost's remainder cents go to
the payer when they share it (they are owed slightly less), otherwise to the
first sharers in name order.
"""
from collections import defaultdict
from decimal import Decimal


def _cents(amount):
    return int((Decimal(amount) * 100).to_integral_value())


def _money(cents):
    return (Decimal(cents) / 100).quantize(Decimal("0.01"))


def shares(amount, payer, sharers):
    """{traveler: cents} for one cost split equally among ``sharers``."""
    total = _cents(amount)
    sharers = sorted(set(sharers) or {payer}, key=lambda t: (t.name, t.pk))
    base, extra = divmod(total, len(sharers))
    split = {t: base for t in sharers}
    lucky = [payer] if payer in split else sharers
    for i in range(extra):
        split[lucky[i % len(lucky)]] += 1
    return split


def summarize(expenses, everyone):
    """Totals and settle-up per currency.

    ``expenses``: TripExpense rows with ``paid_by`` and ``shared_with`` loaded.
    ``everyone``: the trip's travellers (who an empty ``shared_with`` means).
    Returns {currency: {"total", "by_category", "people", "transfers"}} where
    people is [(traveler, paid, share, balance)] and transfers is
    [(debtor, creditor, amount)].
    """
    result = {}
    by_currency = defaultdict(list)
    for expense in expenses:
        by_currency[expense.currency.upper()].append(expense)
    for currency, rows in sorted(by_currency.items()):
        paid, owed, categories = defaultdict(int), defaultdict(int), defaultdict(int)
        for expense in rows:
            cents = _cents(expense.amount)
            paid[expense.paid_by] += cents
            categories[expense.get_category_display()] += cents
            for traveler, share in shares(expense.amount, expense.paid_by,
                                          list(expense.shared_with.all()) or list(everyone)).items():
                owed[traveler] += share
        people = sorted(set(paid) | set(owed), key=lambda t: (t.name, t.pk))
        balance = {t: paid[t] - owed[t] for t in people}
        result[currency] = {
            "total": _money(sum(paid.values())),
            "by_category": sorted(((name, _money(c)) for name, c in categories.items()), key=lambda x: -x[1]),
            "people": [(t, _money(paid[t]), _money(owed[t]), _money(balance[t])) for t in people],
            "transfers": [(d, c, _money(a)) for d, c, a in settle(balance)],
        }
    return result


def settle(balance):
    """Fewest-ish payments that clear ``balance`` ({traveler: cents}, + is owed):
    the largest debtor pays the largest creditor, repeatedly."""
    creditors = sorted(((c, t) for t, c in balance.items() if c > 0), key=lambda x: (-x[0], x[1].name))
    debtors = sorted(((-c, t) for t, c in balance.items() if c < 0), key=lambda x: (-x[0], x[1].name))
    transfers, i, j = [], 0, 0
    creditors = [list(x) for x in creditors]
    debtors = [list(x) for x in debtors]
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][0], creditors[j][0])
        if amount:
            transfers.append((debtors[i][1], creditors[j][1], amount))
        debtors[i][0] -= amount
        creditors[j][0] -= amount
        if debtors[i][0] == 0:
            i += 1
        if creditors[j][0] == 0:
            j += 1
    return transfers


# ------------------------------------------------------------ one currency (site roadmap R10)

class _Converted:
    """An expense seen in another currency, enough for ``summarize`` (settle up in one currency)."""

    def __init__(self, expense, amount, currency):
        self.expense, self.amount, self.currency, self.paid_by = expense, amount, currency, expense.paid_by
        self.shared_with = expense.shared_with

    def get_category_display(self):
        return self.expense.get_category_display()


def rates_for(trip, currencies, dates=()):
    """``apps.core.rates.Rates`` for these currencies with the trip's own rates (two queries)."""
    from apps.core.rates import Rates
    overrides = {(r.from_currency, r.to_currency): r.rate for r in trip.rates.all()}
    return Rates(currencies, dates, overrides)


def in_one_currency(expenses, target, rates):
    """Each expense converted to ``target`` at its ``spent_on`` rate (``expense.converted``, a
    ``Conversion`` or None). Returns {"total", "rows" (for ``summarize``), "used" (the rates, as
    text), "missing" (expenses with no rate: left out of the total, listed)}."""
    rows, used, missing = [], [], []
    for expense in expenses:
        conversion = rates.convert(expense.amount, expense.currency, target, on=expense.spent_on)
        expense.converted = conversion
        if conversion is None:
            missing.append(expense)
            continue
        line = conversion.describe(expense.currency.upper(), target)
        if line and line not in used:
            used.append(line)
        rows.append(_Converted(expense, conversion.amount, target))
    return {"total": _money(sum(_cents(r.amount) for r in rows)), "rows": rows, "used": used, "missing": missing}


def estimate(trip, target):
    """Estimated trip cost in ``target`` from the trip page's prefetch: confirmations' ``cost`` and
    activities' ``est_cost`` (a blank currency counts as ``target``). Queries rates only when
    something is in another currency. Returns None when nothing has a cost."""
    costs = [(c.cost, c.currency or target, "booking") for c in trip.confirmations.all() if c.cost is not None]
    for day in trip.days.all():
        for activity in getattr(day, "ordered_activities", []):
            if activity.est_cost is not None:
                costs.append((activity.est_cost, activity.currency or target, "activity"))
    if not costs:
        return None
    foreign = {currency.upper() for _, currency, _ in costs} - {target.upper()}
    rates = rates_for(trip, foreign | {target}) if foreign else None
    total, used, missing = 0, [], []
    for amount, currency, _ in costs:
        conversion = rates.convert(amount, currency, target) if rates else None
        if rates and conversion is None:
            missing.append(currency.upper())
            continue
        total += _cents(conversion.amount if conversion else amount)
        line = conversion.describe(currency.upper(), target) if conversion else ""
        if line and line not in used:
            used.append(line)
    return {"total": _money(total), "currency": target.upper(), "approx": bool(foreign),
            "bookings": sum(1 for *_, kind in costs if kind == "booking"),
            "activities": sum(1 for *_, kind in costs if kind == "activity"),
            "used": used, "missing": sorted(set(missing))}
