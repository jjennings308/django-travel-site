"""The Help center (docs/plans/help-center.md, H1): every guide in apps/pages/help/ is valid and
its links resolve; the index and guide pages; staff guides gated by can_access_staff."""
import re
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase
from django.urls import Resolver404, resolve, reverse

from apps.pages import helpdocs

User = get_user_model()

HEADER = ("title: {title}\nsummary: A short summary.\naudience: {audience}\nsection: {section}\norder: 10\n"
          "updated: 2026-10-17\n\n# {title}\n\n")


def write(folder, slug, body="Some text.", title="A guide", audience="everyone", section="Trips", header=None):
    text = (header if header is not None else HEADER.format(title=title, audience=audience, section=section)) + body
    Path(folder, f"{slug}.md").write_text(text, encoding="utf-8")


def broken_links(guide, guides):
    """Every link in ``guide`` that doesn't resolve: /help/<slug>/[#anchor] to an existing guide
    (and heading), other site paths through Django's URL resolver. External links are skipped."""
    by_slug = {g.slug: g for g in guides}
    broken = []
    for href in guide.links:
        if re.match(r"^(https?:|mailto:|tel:)", href):
            continue
        path, _, anchor = href.partition("#")
        if not path:  # a link within this guide
            if anchor not in guide.anchors:
                broken.append(href)
            continue
        match = re.fullmatch(r"/help/([\w-]+)/", path)
        if match:
            target = by_slug.get(match.group(1))
            if target is None or (anchor and anchor not in target.anchors):
                broken.append(href)
            continue
        try:
            resolve(path)
        except Resolver404:
            broken.append(href)
    return broken


class EveryGuideTests(SimpleTestCase):
    """The real guides in apps/pages/help/."""

    def test_every_file_parses_with_a_valid_header(self):
        files = sorted(helpdocs.HELP_DIR.glob("*.md"))
        self.assertTrue(files)
        slugs = []
        for path in files:
            with self.subTest(guide=path.name):
                guide = helpdocs.parse(path)  # strict: raises GuideError on a bad header
                self.assertRegex(guide.slug, r"^[a-z0-9-]+$")
                self.assertTrue(guide.html.strip())
                slugs.append(guide.slug)
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(len(helpdocs.all_guides()), len(files))  # none skipped

    def test_every_link_in_every_guide_resolves(self):
        guides = helpdocs.all_guides()
        for guide in guides:
            with self.subTest(guide=guide.slug):
                self.assertEqual(broken_links(guide, guides), [])


class ParserTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name

    def test_bad_headers_are_errors(self):
        cases = {
            "missing": "title: X\nsummary: S\naudience: everyone\nsection: Trips\norder: 1\n\nbody",
            "unknown": HEADER.format(title="X", audience="everyone", section="Trips").replace(
                "order: 10\n", "order: 10\nauthor: me\n"),
            "audience": HEADER.format(title="X", audience="family", section="Trips"),
            "section": HEADER.format(title="X", audience="everyone", section="Misc"),
            "date": HEADER.format(title="X", audience="everyone", section="Trips").replace("2026-10-17", "Oct 17"),
        }
        for slug, header in cases.items():
            write(self.folder, slug, header=header)
            with self.subTest(case=slug), self.assertRaises(helpdocs.GuideError):
                helpdocs.parse(Path(self.folder, f"{slug}.md"))
        self.assertEqual(helpdocs.all_guides(self.folder), ())  # skipped on the site, not a crash

    def test_title_line_dropped_toc_and_scrolling_tables(self):
        write(self.folder, "x", "## One\n\n## Two\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n[next](/help/y/#two)")
        guide = helpdocs.parse(Path(self.folder, "x.md"))
        self.assertNotIn("<h1", guide.html)
        self.assertEqual(guide.toc, (("one", "One"), ("two", "Two")))
        self.assertIn('<div class="help-table"><table>', guide.html)
        self.assertEqual(guide.links, ("/help/y/#two",))

    def test_link_checker_finds_broken_links(self):
        write(self.folder, "a", "## Start\n\n[ok](/help/b/#end) [self](#start) [trips](/trips/) [web](https://x.org)")
        write(self.folder, "b", "## End\n\n[gone](/help/nope/) [anchor](/help/a/#missing) [path](/no/such/page/)")
        guides = helpdocs.all_guides(self.folder)
        by_slug = {g.slug: g for g in guides}
        self.assertEqual(broken_links(by_slug["a"], guides), [])
        self.assertEqual(broken_links(by_slug["b"], guides), ["/help/nope/", "/help/a/#missing", "/no/such/page/"])


class PageTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        folder = self.tmp.name
        write(folder, "reading", "## A\n\n## B\n\n## C\n\nText.", title="Reading your trip", section="Trips")
        write(folder, "short", "Just text.", title="Short one", audience="editors", section="Trips")
        write(folder, "running", "## Queue\n\nStaff only.", title="Running the site", audience="staff", section="Staff")
        patcher = mock.patch.object(helpdocs, "HELP_DIR", Path(folder))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = User.objects.create_user("u", "u@example.com", "pw-1234-abcd")
        self.staff = User.objects.create_user("s", "s@example.com", "pw-1234-abcd")
        self.staff.user_permissions.add(Permission.objects.get(
            codename="can_access_staff_dashboard", content_type__app_label="accounts"))

    def guide_url(self, slug):
        return reverse("pages:help_guide", args=[slug])

    def test_index_lists_public_guides_and_staff_only_for_staff(self):
        page = self.client.get(reverse("pages:help"))
        self.assertContains(page, "The five steps")
        self.assertContains(page, self.guide_url("reading"))
        self.assertContains(page, "For trip editors")
        self.assertNotContains(page, self.guide_url("running"))
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("pages:help")), self.guide_url("running"))

    def test_guide_pages_and_gating(self):
        page = self.client.get(self.guide_url("reading"))
        self.assertContains(page, "Reading your trip")
        self.assertContains(page, "On this page")  # 3 ## headings
        self.assertContains(page, "Updated October 17, 2026")
        self.assertContains(page, self.guide_url("short"))  # related: same section
        self.assertNotContains(self.client.get(self.guide_url("short")), "On this page")
        self.assertEqual(self.client.get(self.guide_url("running")).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.guide_url("running")).status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.guide_url("running")).status_code, 200)
        self.assertEqual(self.client.get(self.guide_url("no-such-guide")).status_code, 404)

    def test_real_guides_render_anonymously(self):
        with mock.patch.object(helpdocs, "HELP_DIR", helpdocs.HELP_DIR.__class__(
                Path(__file__).resolve().parents[1] / "help")):
            for guide in helpdocs.all_guides():
                if guide.audience != "staff":
                    with self.subTest(guide=guide.slug):
                        self.assertEqual(self.client.get(self.guide_url(guide.slug)).status_code, 200)


class LinkedAnchorTests(SimpleTestCase):
    """Anchors other pages link to (help-center plan H4): renaming a heading must fail here."""

    def test_reading_your_trip_keeps_its_sections(self):
        guide = helpdocs.guide("reading-your-trip")
        self.assertIsNotNone(guide)
        self.assertLessEqual({"overview", "days", "reference", "booklet"}, guide.anchors)

    def test_sharing_and_access_keeps_its_sections(self):
        guide = helpdocs.guide("sharing-and-access")
        self.assertLessEqual({"who-can-do-what", "the-public-share-link"}, guide.anchors)


class StaffGuideTests(TestCase):
    """The real staff guide stays staff-only (H3)."""

    def test_running_the_site_is_staff_only(self):
        guide = helpdocs.guide("running-the-site")
        self.assertEqual(guide.audience, "staff")
        url = reverse("pages:help_guide", args=["running-the-site"])
        self.assertNotContains(self.client.get(reverse("pages:help")), url)
        self.assertEqual(self.client.get(url).status_code, 404)
        user = User.objects.create_user("u", "u@example.com", "pw-1234-abcd")
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 404)
        user.user_permissions.add(Permission.objects.get(codename="can_access_staff_dashboard",
                                                         content_type__app_label="accounts"))
        self.client.force_login(User.objects.get(pk=user.pk))
        self.assertEqual(self.client.get(url).status_code, 200)
