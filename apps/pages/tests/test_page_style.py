"""One look for page titles and list filters (docs/plans/ux-consistency.md, V2): every page's <h1> uses the shared
title classes, and every catalogue / bucket-list list page uses the shared filter bar."""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

User = get_user_model()

TITLE_CLASSES = {"sbl-page-title", "sbl-dialog-title", "page-title", "hero-title"}

#: Pages whose <h1> is a banner, not a page title: the public home page's marketing hero. (The signed-in Home's
#: greeting became a page header in V5.)
BANNERS = {"/"}

#: Prefixes never walked: auth flows that sign the client out or need tokens, the admin, files and feeds.
SKIP = (
    "/admin/",
    "/accounts/logout/",
    "/__reload__/",
    "/sw.js",
    "/manifest.webmanifest",
    "/robots.txt",
    "/sitemap.xml",
)

LIST_PAGES = (
    "activities:activity_list",
    "events:event_list",
    "bucketlists:dashboard",
    "locations:country_list",
    "locations:region_list",
    "locations:city_list",
    "locations:poi_list",
)


def plain_urls(resolver=None, prefix=""):
    """Every URL in the conf that takes no arguments."""
    resolver = resolver or get_resolver()
    for pattern in resolver.url_patterns:
        route = str(pattern.pattern)
        if "<" in route or "(?P" in route or "\\" in route:
            continue
        route = route.lstrip("^").rstrip("$")
        if isinstance(pattern, URLResolver):
            yield from plain_urls(pattern, prefix + route)
        elif isinstance(pattern, URLPattern):
            yield "/" + (prefix + route).lstrip("/")


def h1_classes(html):
    return [set((m.group(1) or "").split()) for m in re.finditer(r'<h1(?:\s[^>]*?class="([^"]*)")?[^>]*>', html)]


class PageTitleTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            "staff", "staff@example.com", "pw-1234-abcd", is_staff=True, is_superuser=True
        )
        self.member = User.objects.create_user("member", "member@example.com", "pw-1234-abcd")

    def test_every_page_title_uses_the_shared_classes(self):
        urls = sorted({u for u in plain_urls() if not u.startswith(SKIP) and u not in BANNERS})
        self.assertGreater(len(urls), 40)
        wrong = []
        for user in (self.member, self.staff):
            self.client.force_login(user)
            for url in urls:
                response = self.client.get(url)
                if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
                    continue
                for classes in h1_classes(response.content.decode()):
                    if not classes & TITLE_CLASSES:
                        wrong.append(f"{url} ({user.username}): {' '.join(sorted(classes)) or 'no class'}")
        self.assertEqual(
            wrong, [], "pages whose <h1> isn't sbl-page-title / sbl-dialog-title / page-title / hero-title"
        )

    def test_list_pages_use_the_filter_bar(self):
        self.client.force_login(self.member)
        for name in LIST_PAGES:
            with self.subTest(name):
                html = self.client.get(reverse(name)).content.decode()
                self.assertIn("data-filter-bar", html)
                self.assertIn("data-filter-go", html)
                self.assertNotIn("data-filter-clear", html)  # nothing filtered yet

    def test_clear_shows_once_filtered_and_keeps_the_page_context(self):
        self.client.force_login(self.member)
        html = self.client.get(reverse("activities:activity_list") + "?q=castle&sort=name").content.decode()
        self.assertIn("data-filter-clear", html)
        self.assertIn(f'href="{reverse("activities:activity_list")}"', html)
        sorted_only = self.client.get(reverse("activities:activity_list") + "?sort=name").content.decode()
        self.assertNotIn("data-filter-clear", sorted_only)  # a sort order isn't a filter
        # keep= stays on Clear (an activity's own dates), page and ignore= don't count
        from django.template import Context, Template
        from django.test import RequestFactory

        bar = Template(
            '{% load filter_tags %}{% filter_bar count=3 ignore="when" keep="activity" %}{% endfilter_bar %}'
        )
        from django.contrib.auth.models import AnonymousUser

        def render(query):
            request = RequestFactory().get("/events/" + query)
            request.user = AnonymousUser()
            return bar.render(Context({"request": request}))

        self.assertIn(
            'href="/events/?activity=oktoberfest" class="sbl-link" data-filter-clear',
            render("?activity=oktoberfest&q=x"),
        )
        self.assertNotIn("data-filter-clear", render("?activity=oktoberfest&when=past&page=2"))
        self.assertIn("3 results", render(""))
