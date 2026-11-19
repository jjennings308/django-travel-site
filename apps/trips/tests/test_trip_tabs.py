"""The trip's tab bar and header actions (docs/plans/ux-consistency.md, V3): Overview and the trip-wide views on the
trip page and each of them, the current one marked; counts only from what the page already has; Settings an outline
button; the PDF and More actions menus as icon buttons with their labels."""

import re

from django.urls import reverse

from apps.trips.tests.helpers import make_task
from apps.trips.tests.test_page_shell import Fixture

TABS = (
    ("trip_detail", "Overview"),
    ("trip_bookings", "Bookings"),
    ("trip_todo", "To do"),
    ("trip_map", "Map"),
    ("trip_budget", "Budget"),
    ("trip_photos", "Photos"),
    ("trip_people", "People"),
    ("trip_history", "History"),
)


def tab_bar(html):
    found = re.search(r'<nav class="trip-tabs" aria-label="Trip sections" data-trip-tabs>(.*?)</nav>', html, re.S)
    return found.group(1) if found else None


class TabBarTests(Fixture):
    def test_every_section_shows_the_bar_with_itself_current(self):
        self.client.force_login(self.viewer)
        for name, label in TABS:
            with self.subTest(name):
                url = reverse(f"trips:{name}", args=[self.trip.pk])
                bar = tab_bar(self.client.get(url).content.decode())
                self.assertIsNotNone(bar, "no tab bar")
                for other, _ in TABS:
                    self.assertIn(f'href="{reverse(f"trips:{other}", args=[self.trip.pk])}"', bar)
                current = re.findall(r'<a href="([^"]*)" aria-current="page"[^>]*>([^<]*)', bar)
                self.assertEqual(current, [(url, label)])

    def test_sub_page_breadcrumbs_end_at_the_trip(self):
        self.client.force_login(self.viewer)
        html = self.client.get(reverse("trips:trip_bookings", args=[self.trip.pk])).content.decode()
        trail = re.search(r'<nav[^>]*aria-label="Breadcrumb".*?</nav>', html, re.S).group(0)
        self.assertIn(f'href="{reverse("trips:trip_detail", args=[self.trip.pk])}"', trail)
        self.assertIn("Europe", trail)
        self.assertNotIn("Bookings", trail)  # the tab says which section this is

    def test_open_to_dos_are_counted_where_the_page_has_them(self):
        make_task(self.trip, "Book the castle")
        make_task(self.trip, "Book the train")
        self.client.force_login(self.viewer)
        for name in ("trip_detail", "trip_todo"):
            with self.subTest(name):
                bar = tab_bar(self.client.get(reverse(f"trips:{name}", args=[self.trip.pk])).content.decode())
                self.assertIn('To do <span class="trip-tab-count" title="Open to-dos">2</span>', bar)
        bar = tab_bar(self.client.get(reverse("trips:trip_photos", args=[self.trip.pk])).content.decode())
        self.assertNotIn("trip-tab-count", bar)  # Photos doesn't load the to-dos, so no number (and no query)


class HeaderActionTests(Fixture):
    def test_settings_is_an_outline_button_and_the_menus_are_labelled_icons(self):
        html = self.page(self.editor).content.decode()
        self.assertRegex(html, r'<a class="btn-quiet" href="[^"]*/settings/" data-settings-link><i class="bi bi-gear"')
        self.assertNotIn('class="btn" href="' + reverse("trips:trip_settings", args=[self.trip.pk]), html)
        self.assertIn('aria-label="More PDF choices"', html)
        self.assertIn('<i class="bi bi-chevron-down" aria-hidden="true"></i>', html)
        self.assertRegex(html, r'aria-label="More actions"[^>]*data-trip-menu><i class="bi bi-three-dots"')
        for old in ("▾</button>", "⋯</button>"):
            self.assertNotIn(old, html)
