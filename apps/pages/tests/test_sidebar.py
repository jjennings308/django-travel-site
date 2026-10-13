"""The sidebar follows the lifecycle: Discover → Dream → Pick a date → Plan → Done."""
import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

ACTIVE = re.compile(r'bg-earth-sand[^"]*"[^>]*>\s*<i[^>]*></i>([^<]+)')


class SidebarTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("u", "u@example.com", "pw-1234-abcd"))

    def nav(self, url):
        html = self.client.get(url).content.decode()
        start = html.index('aria-label="Main"')
        return html[start:html.index("</nav>", start)]

    def test_stages_in_order(self):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", self.nav(reverse("pages:dashboard"))))
        positions = [text.index(s) for s in ("Discover", "Activities", "Events", "Places", "Dream", "My bucket list",
                                             "Pick a date", "My dates", "Plan", "Trips", "Done", "My adventures")]
        self.assertEqual(positions, sorted(positions))

    def test_one_active_item(self):
        bucket = reverse("bucketlists:dashboard")
        for url, label in ((reverse("pages:dashboard"), "Home"), (bucket, "My bucket list"),
                           (reverse("bucketlists:adventures"), "My adventures"), (reverse("events:event_list"), "Events"),
                           (reverse("bucketlists:dates"), "My dates"),
                           (reverse("trips:trip_list"), "Trips"), (reverse("activities:activity_list"), "Activities")):
            with self.subTest(url=url):
                self.assertEqual(ACTIVE.findall(self.nav(url)), [label])

    def test_sections_fold_and_the_current_one_starts_open(self):
        nav = self.nav(reverse("trips:trip_list"))
        self.assertEqual(nav.count('@click="toggle()"'), 5)  # one toggle per numbered section
        sections = {m.group(1): m.group(0) for m in re.finditer(r"sbl-nav-(\w+)[^\"]*", nav)}
        opened = re.findall(r"open: true, toggle\(\) \{[^}]*sbl-nav-(\w+)", nav)
        self.assertEqual(opened, ["plan"])  # on a trips page, Plan is forced open
        self.assertEqual(set(sections), {"discover", "dream", "dates", "plan", "done"})
        self.assertIn("Home", nav)
        self.assertIn("About", nav)
