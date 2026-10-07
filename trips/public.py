"""The public, non-detailed shape of a trip.

This is the serializer layer the roadmap asked for, and it exists so that *one*
place decides what leaves the app. The rule it enforces is simple:

    **Structure yes, prose no.**

Enumerated choices and short authored headings are published; free prose is
not. Everything here is a JSON-compatible dict, so the HTML view and a future
JSON API render from the same call — the template below cannot be handed a model
instance and accidentally print a field this module did not choose.

What that costs, measured against the real data rather than guessed:

- ``Trip.name`` embeds the travellers ("James & Regan — Taos"), so the public
  title is derived from ``destination`` and the dates instead. See
  ``Trip.public_title``.
- ``Section`` is **omitted entirely**, not filtered. ``Section.content`` is a
  free-text JSON blob and it contains traveller first names — "Afternoon — Olga
  Leads", "Windsor to LHR", "At Munich Airport — The Group Splits". There is no
  per-key allowlist for prose, and a name scrubber is worse than useless here:
  it would have to mangle "James Beard Award winner" and "St. James Hotel" while
  still missing any traveller added to the roster tomorrow. A day reports how
  many activities it has, and the text stays inside the app.
- ``Lodging``, ``TransportLeg``, ``Confirmation``, ``Contact`` and
  ``BookingTask`` are omitted as whole models for the same reason: the
  confirmation numbers are the point, but so are the "Guest Name: James
  Jennings" strings sitting in ``Lodging.notes`` next to them.
- ``Meal.why_recommended`` and ``Meal.reservation_notes`` are prose and are
  dropped; the name, type, cuisine and price band are not, so a public page can
  still say what the food is like.

The allowlists are declared as data (``TRIP_FIELDS``, ``DAY_FIELDS``,
``MEAL_FIELDS``) rather than spelled inline, because they are the thing a test
has to check the output against. ``ShapeTests`` asserts the output keys are a
subset of these, which is what makes "a field added to the model tomorrow cannot
leak" a checked property instead of a claim in a comment.

Dates come through as ``date`` objects rather than strings, because the template
formats them with ``|date`` and a pre-formatted string would be locale-blind in
the other direction. ``json.dumps(shape, cls=DjangoJSONEncoder)`` is the call a
future JSON API makes; ``find_leaks`` does exactly that.

Adding to this module means choosing to publish something. Anything added to a
*model* is invisible here until it is added here, which is the entire point.
"""
import json
import re

from django.core.serializers.json import DjangoJSONEncoder

from trips.models import Meal, Trip

#: Fields of ``Trip`` the public page may show. ``name``, ``notes``, ``status``,
#: ``travelers``, ``created_by`` and ``deleted_at`` are all absent, and their
#: absence is the design.
TRIP_FIELDS = (
    "destination",
    "start_date",
    "end_date",
)

#: Fields of ``Day``. ``theme`` is **not** here, and that is the one judgement in
#: this module worth arguing with.
#:
#: ``Day.theme`` reads like a heading, so it is tempting to keep it — and the
#: Taos themes ("Taos Culture Day", "Enchanted Circle Loop") are exactly what
#: would make a public page worth reading. Measured against the Europe draft it
#: is not safe: of 17 days, 4 leak. Two carry flight routes ("Overnight flight —
#: Pittsburgh (PIT) → Frankfurt (FRA)", "London Heathrow (LHR) → Pittsburgh
#: (PIT)") and one reads "Fly to England | Sara & Henry fly home", which names
#: two travellers *and* publishes who goes home early.
#:
#: So it is prose by another name, and prose does not go out. The alternative —
#: a review checkbox — was considered and declined: it replaces a guarantee the
#: code can make with a promise somebody has to remember, which is the opposite
#: of why this module exists.
DAY_FIELDS = (
    "day_number",
    "date",
    "meals_included",
)

#: Fields of ``Meal``. No ``why_recommended``, no ``reservation_notes``: both are
#: prose written by the importers and both have carried personal detail.
MEAL_FIELDS = (
    "name",
    "meal_type",
    "cuisine",
    "price_range",
)


def _label(value, choices):
    """The human-readable half of a ``choices`` value, or ``""`` if unset."""
    if not value:
        return ""
    return dict(choices).get(value, value)


def public_trip(trip):
    """Serialize ``trip`` for the public page.

    Takes a ``Trip`` that the caller has already resolved from a token — this
    module does not decide access, it only decides shape. That split is
    deliberate: the token check is ``TripQuerySet.public``, which knows about
    grants and soft deletion, and neither belongs in a serializer.

    The caller must prefetch ``days__meals`` and ``days__sections``; a day with
    either one unprefetched costs a query, so a 25-day trip goes from two queries
    to fifty. ``len(...)`` on the relation rather than ``.count()``, because
    ``.count()`` goes to the database even when the relation is already
    prefetched. ``PublicQueryCountTests`` pins the total.
    """
    return {
        "title": trip.public_title,
        "destination": trip.destination,
        "start_date": trip.start_date,
        "end_date": trip.end_date,
        "nights": trip.nights,
        "budget": _label(trip.budget, Trip.Budget.choices),
        "structure": _label(trip.structure, Trip.Structure.choices),
        "days": [_public_day(day) for day in trip.days.all()],
    }


def _public_day(day):
    return {
        "day_number": day.day_number,
        "date": day.date,
        "meals_included": day.meals_included,
        # A count, never the sections. See the module docstring: their content is
        # prose that carries traveller names.
        "activity_count": len(day.sections.all()),
        "meals": [_public_meal(meal) for meal in day.meals.all()],
    }


def _public_meal(meal):
    return {
        "name": meal.name,
        "meal_type": _label(meal.meal_type, Meal.MealType.choices),
        "cuisine": meal.cuisine,
        "price_range": meal.price_range,
    }


# -- checking ---------------------------------------------------------------
#
# The allowlist is a claim; this is the receipt. `find_leaks` is shared by the
# `audit_public_leak` command, which runs it over every row in the real database,
# and by the tests, which run it over fixtures. That split exists because the
# checks worth running are the ones about *real* data — every leak found so far
# was prose a synthetic fixture would never have contained — and a test cannot
# reach the development database without being the thing CLAUDE.md warns about.

#: Patterns that catch the shapes a leak tends to take when it is not a name.
#: ``certain`` because these have no false positives in practice: a booking
#: reference or an airport code in public output is a leak whatever else it is.
#:
#: The route pattern has to tolerate a closing bracket, because the real data
#: writes "Pittsburgh (PIT) → Frankfurt (FRA)" — a strict `AAA → BBB` misses
#: every airport code in this project. Hence the separate parenthesised-code
#: pattern as well, which is what actually catches those.
LEAK_PATTERNS = (
    (
        r"\(?[A-Z]{3}\)?\s*(?:→|->)\s*\(?[A-Z]{3}",
        "a flight route",
        "certain",
    ),
    (
        r"\([A-Z]{3}\)",
        "an airport code (the only parenthesised 3-letter codes in this data)",
        "certain",
    ),
    (
        r"confirmation\s*(?:number|ref|code|#|:)?\s*[A-Z0-9]{5,}",
        "a confirmation number",
        "certain",
    ),
    (r"\b\d{7,}\b", "a long numeric code", "certain"),
)


def find_leaks(shape, names=(), numbers=(), patterns=LEAK_PATTERNS):
    """Everything in a serialized shape that looks like it should not be public.

    ``names`` is any sequence of words to treat as forbidden — pass every word of
    every traveller's name, not the full name, because the leaks are first-name
    references inside prose rather than the roster itself.

    Returns ``[(severity, description), ...]``, empty when the shape is clean.

    Two severities, because a first name is very often also a place name: the
    real data has a restaurant called "St. James Hotel" on a trip with a
    traveller called James, and treating that as a hard failure would mean the
    check can never pass. ``certain`` findings are things that are a leak
    whatever their context — a booking reference, a numeric code, a flight
    route. ``possible`` findings are name words, which need a human to say
    whether "St. James Hotel" is a guest or a building.

    Deliberately a *heuristic*: it cannot prove a shape is safe, only that these
    specific things are absent. The allowlist is what makes it safe; this is what
    notices when someone weakens the allowlist.
    """
    # `DjangoJSONEncoder` rather than `str()` because dates must be rendered for
    # the regexes to see them, not as `datetime.date(2027, 9, 17)`.
    blob = json.dumps(shape, cls=DjangoJSONEncoder)
    lowered = blob.lower()
    findings = []

    for word in names:
        word = str(word).strip().lower()
        # Anything under three characters ("Bo", "Al") is noise: it matches
        # inside ordinary words and would report on every shape.
        if len(word) < 3:
            continue
        if re.search(r"\b%s\b" % re.escape(word), lowered):
            findings.append(("possible", f"traveller name {word!r}"))
    for number in numbers:
        if number and str(number) in blob:
            findings.append(("certain", f"confirmation number {number!r}"))
    for pattern, description, severity in patterns:
        match = re.search(pattern, blob, re.IGNORECASE)
        if match:
            findings.append((severity, f"{description} ({match.group(0)!r})"))
    return findings


def trip_leak_finders(trip):
    """The names and numbers that must not appear in ``trip``'s public shape.

    Collected from the trip's own rows, so the check follows the data: a new
    confirmation number needs no edit here to be tested.
    """
    names = set()
    for traveler in trip.travelers.all():
        for word in traveler.name.split():
            names.add(word)
    numbers = set()
    for source in (
        list(trip.confirmations.all())
        + list(trip.lodging.all())
        + list(trip.transport.all())
    ):
        value = getattr(source, "confirmation_number", "")
        if value:
            numbers.add(value)
    return names, numbers