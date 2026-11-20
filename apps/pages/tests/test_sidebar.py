"""The sidebar (ux-consistency V5): Home, Discover, then Your journey — the lifecycle as a numbered rail with each
stage as a caption — then About and Help. Nothing folds; the current page is marked."""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SidebarTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd"))

    def nav(self, url):
        html = self.client.get(url).content.decode()
        start = html.index('aria-label="Main"')
        return html[start : html.index("</nav>", start)]

    def text(self, html):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))

    def test_order_and_captions(self):
        text = self.text(self.nav(reverse("pages:dashboard")))
        order = (
            "Home",
            "Discover",
            "Activities",
            "Events",
            "Places",
            "Your journey",
            "1 Bucket list Dream",
            "2 My dates Pick a date",
            "3 Trips Plan",
            "4 Adventures Done",
            "Albums",
            "About",
            "Help",
        )
        positions = [text.index(label) for label in order]
        self.assertEqual(positions, sorted(positions))

    def test_the_current_page_is_marked_once(self):
        for url, nav in (
            (reverse("pages:dashboard"), "home"),
            (reverse("bucketlists:dashboard"), "bucket"),
            (reverse("bucketlists:dates"), "dates"),
            (reverse("trips:trip_list"), "trips"),
            (reverse("bucketlists:adventures"), "adventures"),
            (reverse("bucketlists:albums"), "albums"),
            (reverse("events:event_list"), "events"),
            (reverse("activities:activity_list"), "activities"),
            (reverse("pages:help"), "help"),
        ):
            with self.subTest(url=url):
                html = self.nav(url)
                current = re.findall(r'<a [^>]*aria-current="page"[^>]*>|<a [^>]*>', html)
                marked = [re.search(r'data-nav="(\w+)"', a).group(1) for a in current if 'aria-current="page"' in a]
                self.assertEqual(marked, [nav])

    def test_nothing_folds(self):
        nav = self.nav(reverse("trips:trip_list"))
        self.assertNotIn("toggle()", nav)
        self.assertNotIn("sbl-nav-", nav)
        self.assertNotIn("localStorage", nav)


class HeaderTests(TestCase):
    def test_no_duplicate_navigation_in_the_header(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd"))
        html = self.client.get(reverse("pages:dashboard")).content.decode()
        header = html[html.index("<header") : html.index('aria-label="Navigation"')]  # the bar, not the phone drawer
        for name in ("pages:dashboard", "bucketlists:dashboard", "trips:trip_list"):
            self.assertNotIn(f'href="{reverse(name)}"', header, name)
