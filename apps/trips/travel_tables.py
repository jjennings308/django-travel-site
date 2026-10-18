"""Turn logistics tables' "A → B" rows into transport legs (Phase C of
docs/plans/trip-items-and-confirmations.md).

One plan, three callers: the per-section "Turn into legs" page, the trip-wide review and
``manage.py convert_travel_tables``. ``plan(trip, sections)`` reads every table and says, per
row, whether it is already a leg on that day (**link**: the leg is placed in the section and
gains what it lacks, never overwritten) or not (**create** a planned leg). Nothing is saved
until ``apply``; times are never guessed.

``apply`` converts each section that had at least one ticked row: it becomes a ``travel``
section (title kept), linked and created rows leave its rows, "Total…" rows go (the day's
total is computed from its legs; their other text is added to the last leg's notes), and the
remaining rows stay as reference rows (a Bayern Ticket's price and what it covers).
"""
from dataclasses import dataclass, field

from django.db import transaction

from .logistics import match_city, proposed_legs, total_notes
from .models import Section, TransportLeg


def _norm(text):
    return " ".join((text or "").lower().split())


def _contains(outer, inner):
    import re
    outer, inner = _norm(outer), _norm(inner)
    return bool(inner) and re.search(r"(?<!\w)" + re.escape(inner) + r"(?!\w)", outer) is not None


def _same_hop(row, leg, a, b, city_for):
    """Is this table row the leg? Same wording, same city pair, or each end of one names the
    other's ("Depart ABQ" / "ABQ", "Butzbach" / "Butzbach Hof")."""
    if (_norm(row["origin"]), _norm(row["destination"])) == (_norm(leg.origin), _norm(leg.destination)):
        return True
    la = leg.origin_city or city_for(leg.origin)
    lb = leg.destination_city or city_for(leg.destination)
    if a is not None and b is not None and la is not None and lb is not None and (a.pk, b.pk) == (la.pk, lb.pk):
        return True
    ends = ((row["origin"], leg.origin), (row["destination"], leg.destination))
    return all(_contains(x, y) or _contains(y, x) for x, y in ends)


@dataclass
class SectionPlan:
    section: Section
    day: object
    rows: list = field(default_factory=list)  # proposal dicts, see plan()
    totals: list = field(default_factory=list)  # [{"row", "note"}]

    @property
    def to_do(self):
        return any(r["include"] for r in self.rows)


def city_finder(trip):
    """``city_for(text)``: a city named in ``text``, the trip's own first, then the catalogue."""
    from apps.approval_system.models import ApprovalStatus
    from apps.locations.models import City
    trip_cities = list(trip.cities.select_related("country"))
    catalogue = None

    def city_for(text):
        nonlocal catalogue
        found = match_city(text, trip_cities)
        if found is None:
            if catalogue is None:
                catalogue = list(City.objects.filter(approval_status=ApprovalStatus.APPROVED).select_related("country"))
            found = match_city(text, catalogue)
        return found
    city_for.trip_cities = trip_cities
    return city_for


def logistics_sections(trip):
    """The trip's logistics tables that have at least one hop, in day order."""
    sections = (Section.objects.filter(day__trip=trip, section_type=Section.Type.LOGISTICS_TABLE)
                .select_related("day").order_by("day__date", "day__day_number", "order", "id"))
    return [s for s in sections if proposed_legs((s.content or {}).get("columns"), (s.content or {}).get("rows"))]


def plan(trip, sections, city_for=None):
    """A ``SectionPlan`` per section. Each row dict is a ``proposed_legs`` proposal plus:
    ``date``, ``origin_city`` / ``destination_city`` (City or None), ``leg`` (the existing
    leg it matches, or None), ``action`` ("link" / "create") and ``include`` (ticked: arrow
    rows, never "possible" ones)."""
    city_for = city_for or city_finder(trip)
    dates = {s.day.date for s in sections}
    legs_by_date = {}
    for leg in TransportLeg.objects.filter(trip=trip, date__in=dates).select_related("origin_city", "destination_city"):
        legs_by_date.setdefault(leg.date, []).append(leg)
    plans = []
    for section in sections:
        content = section.content or {}
        columns, rows = content.get("columns"), content.get("rows")
        taken = set()
        section_plan = SectionPlan(section=section, day=section.day, totals=total_notes(columns, rows))
        for proposal in proposed_legs(columns, rows):
            a, b = city_for(proposal["origin"]), city_for(proposal["destination"])
            match = next((leg for leg in legs_by_date.get(section.day.date, [])
                          if leg.pk not in taken and _same_hop(proposal, leg, a, b, city_for)), None)
            if match is not None:
                taken.add(match.pk)
            section_plan.rows.append({
                **proposal, "date": section.day.date, "origin_city": a, "destination_city": b,
                "leg": match, "action": "link" if match else "create",
                "include": proposal["strength"] == "arrow",
            })
        plans.append(section_plan)
    return plans


def apply(trip, plans, chosen):
    """Carry out ``plans``. ``chosen`` maps ``(section_pk, row)`` to the reviewed values for
    each ticked row (``date``, ``mode``, ``origin``, ``destination``, ``origin_city``,
    ``destination_city``, ``operator``, ``notes``, ``duration``); rows not in it are left as
    they are. Returns ``{"created": [...], "linked": [...], "sections": n}``."""
    from .changes import batch
    created, linked, converted = [], [], 0
    with transaction.atomic(), batch("Turned travel tables into journeys", trip=trip):
        for section_plan in plans:
            section = section_plan.section
            ticked = [r for r in section_plan.rows if (section.pk, r["row"]) in chosen]
            if not ticked:
                continue
            content = dict(section.content or {})
            section.section_type = Section.Type.TRAVEL
            section.save(update_fields=["section_type"])
            day_date = section_plan.day.date
            placed = []
            for row in ticked:
                data = chosen[(section.pk, row["row"])]
                if row["leg"] is not None:
                    leg = row["leg"]
                    changed = ["section"]
                    leg.section = section if leg.date == day_date else leg.section
                    for name, value in (("est_duration", data.get("duration")), ("operator", data.get("operator")),
                                        ("notes", data.get("notes"))):
                        if value and not getattr(leg, name):
                            setattr(leg, name, value)
                            changed.append(name)
                    leg.save(update_fields=changed)
                    linked.append(leg)
                else:
                    leg = TransportLeg.objects.create(
                        trip=trip, date=data["date"], mode=data["mode"], origin=data["origin"],
                        destination=data["destination"], origin_city=data.get("origin_city"),
                        destination_city=data.get("destination_city"), operator=data.get("operator") or "",
                        notes=data.get("notes") or "", est_duration=data.get("duration"), order=row["row"],
                        section=section if data["date"] == day_date else None)
                    created.append(leg)
                    for city in (leg.origin_city, leg.destination_city):
                        if city is not None:
                            trip.cities.add(city)
                placed.append(leg)
            notes = [t["note"] for t in section_plan.totals if t["note"]]
            if notes and placed:
                last = placed[-1]
                last.notes = " · ".join([n for n in [last.notes] + notes if n])
                last.save(update_fields=["notes"])
            gone = {r["row"] for r in ticked} | {t["row"] for t in section_plan.totals}
            left = [r for i, r in enumerate(content.get("rows") or []) if i not in gone]
            converted += 1
            if not left and not any(leg.section_id == section.pk for leg in placed):
                section.delete()  # nothing left to show: its legs all moved to other days
                continue
            content["rows"] = left
            if not left:
                content.pop("columns", None)
                content.pop("rows", None)
            section.content = content
            section.save(update_fields=["content"])
    return {"created": created, "linked": linked, "sections": converted}


def automatic_choices(plans):
    """The review's defaults: every ticked (arrow) row, as planned."""
    return {(p.section.pk, row["row"]): row for p in plans for row in p.rows if row["include"]}


def convert_automatically(trip):
    """Convert the trip's tables with the automatic choices (``import_itinerary``,
    ``convert_travel_tables --apply``). Returns ``apply``'s result."""
    plans = plan(trip, logistics_sections(trip))
    chosen = automatic_choices(plans)
    if not chosen:
        return {"created": [], "linked": [], "sections": 0}
    return apply(trip, plans, chosen)


def has_pending(days):
    """Does any of these (prefetched) days still have a logistics table with an arrow row?
    Reads the ``day.ordered_sections`` prefetch only: no query."""
    for day in days:
        for section in getattr(day, "ordered_sections", []):
            if section.section_type != Section.Type.LOGISTICS_TABLE:
                continue
            content = section.content or {}
            if any(p["strength"] == "arrow" for p in proposed_legs(content.get("columns"), content.get("rows"))):
                return True
    return False
