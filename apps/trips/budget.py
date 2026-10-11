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
