"""The Help center's guides (docs/plans/help-center.md): one markdown file per guide in
``apps/pages/help/``, with a metadata header, served at ``/help/<slug>/`` (``pages:help_guide``).

A guide file::

    title: How to add a day to your trip
    summary: Add a day, fill in its details, then add legs, activities and meals to it.
    audience: editors
    section: Trips
    order: 20
    updated: 2026-10-16

    # How to add a day to your trip
    …body…

The header is Python-Markdown ``meta`` lines, then a blank line; every key in ``REQUIRED_KEYS`` is
needed and no other is allowed. The body's leading ``# Title`` line is dropped (the page shows
``title``). Guides are trusted, committed content (never user-submitted), so their HTML is not
sanitised — and they never contain secrets, server names or deploy steps.

``all_guides()`` parses the folder once per set of file names and modification times, so an edited
guide shows without a restart. A guide that fails to parse is skipped and logged on the site;
``tests/test_help.py`` parses each one strictly (``parse``) so a bad guide fails the suite instead.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import markdown

log = logging.getLogger(__name__)

HELP_DIR = Path(__file__).resolve().parent / "help"
SECTIONS = ("Getting started", "Trips", "Bookings & contacts", "Bucket list", "Places & events", "Staff")
# audience -> the tag shown beside a guide in the index ("" for everyone).
AUDIENCES = {"everyone": "", "editors": "For trip editors", "staff": "Staff"}
REQUIRED_KEYS = ("title", "summary", "audience", "section", "order", "updated")
EXTENSIONS = ["meta", "tables", "fenced_code", "toc", "sane_lists"]
HREF = re.compile(r'href="([^"]+)"')


class GuideError(ValueError):
    """A guide file is malformed (the message names the file and the problem)."""


@dataclass(frozen=True)
class Guide:
    slug: str
    title: str
    summary: str
    audience: str
    section: str
    order: int
    updated: date
    html: str
    toc: tuple = ()  # ((anchor id, heading text), …) for the body's ## headings
    links: tuple = field(default=(), repr=False)  # every href in the body, for the link checker

    @property
    def tag(self):
        return AUDIENCES.get(self.audience, "")

    @property
    def anchors(self):
        return {anchor for anchor, _name in self.toc}


def _split(text):
    """(header lines, body) — the header runs to the first blank line."""
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        blank = lines.index("")
    except ValueError:
        return lines, ""
    return lines[:blank], "\n".join(lines[blank + 1:])


def parse(path):
    """One guide from its file, or ``GuideError``."""
    path = Path(path)
    name = path.name
    header, body = _split(path.read_text(encoding="utf-8"))
    meta = {}
    for line in header:
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise GuideError(f"{name}: header line {line!r} is not 'key: value'")
        meta[key.strip().lower()] = value.strip()
    missing = [key for key in REQUIRED_KEYS if not meta.get(key)]
    if missing:
        raise GuideError(f"{name}: missing {', '.join(missing)}")
    unknown = sorted(set(meta) - set(REQUIRED_KEYS))
    if unknown:
        raise GuideError(f"{name}: unknown header key(s) {', '.join(unknown)}")
    if meta["audience"] not in AUDIENCES:
        raise GuideError(f"{name}: audience must be one of {', '.join(AUDIENCES)}")
    if meta["section"] not in SECTIONS:
        raise GuideError(f"{name}: section must be one of {', '.join(SECTIONS)}")
    try:
        order = int(meta["order"])
        updated = date.fromisoformat(meta["updated"])
    except ValueError as exc:
        raise GuideError(f"{name}: order must be a whole number and updated an ISO date ({exc})") from exc

    body = re.sub(r"\A\s*#\s[^\n]*\n", "", body, count=1)  # the page shows the title itself
    md = markdown.Markdown(extensions=EXTENSIONS, extension_configs={"toc": {"permalink": False}})
    html = md.convert(body)
    # Tables scroll sideways inside their own box on a phone.
    html = html.replace("<table>", '<div class="help-table"><table>').replace("</table>", "</table></div>")
    toc = tuple((token["id"], token["name"]) for token in _flatten(md.toc_tokens) if token["level"] == 2)
    return Guide(slug=path.stem, title=meta["title"], summary=meta["summary"], audience=meta["audience"],
                 section=meta["section"], order=order, updated=updated, html=html, toc=toc,
                 links=tuple(HREF.findall(html)))


def _flatten(tokens):
    for token in tokens:
        yield token
        yield from _flatten(token.get("children", []))


@lru_cache(maxsize=4)
def _load(folder, signature):
    guides = []
    for name, _mtime in signature:
        try:
            guides.append(parse(Path(folder) / name))
        except GuideError as exc:  # never let one bad file break /help/; the test suite catches it
            log.error("Help guide skipped: %s", exc)
    return tuple(sorted(guides, key=lambda g: (SECTIONS.index(g.section), g.order, g.title)))


def all_guides(folder=None):
    """Every valid guide, in section then ``order`` order."""
    folder = Path(folder or HELP_DIR)
    files = sorted(folder.glob("*.md"))
    signature = tuple((path.name, path.stat().st_mtime_ns) for path in files)
    return _load(str(folder), signature)


def is_visible(guide, user):
    return guide.audience != "staff" or bool(getattr(user, "can_access_staff", False))


def visible_to(user, folder=None):
    return [g for g in all_guides(folder) if is_visible(g, user)]


def guide(slug, folder=None):
    return next((g for g in all_guides(folder) if g.slug == slug), None)


def grouped(user, folder=None):
    """[(section, [guide, …])] for the index, in ``SECTIONS`` order, empty sections left out."""
    guides = visible_to(user, folder)
    return [(section, [g for g in guides if g.section == section])
            for section in SECTIONS if any(g.section == section for g in guides)]
