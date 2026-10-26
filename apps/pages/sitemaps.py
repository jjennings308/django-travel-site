"""sitemap.xml and robots.txt (site roadmap R22). Addresses are built from ``SITE_URL`` (never the request's
host), and only published items are listed: approved places, public approved activities, approved events
from a year ago on, the help guides for everyone and the public pages. Members' bucket lists are left out."""
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sitemaps import Sitemap
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from apps.activities.models import Activity
from apps.approval_system.models import ApprovalStatus
from apps.events.models import Event
from apps.locations.models import POI, City, Country, Region

from . import helpdocs


class SiteSitemap(Sitemap):
    """A Sitemap on SITE_URL's scheme and host."""

    def get_protocol(self, protocol=None):
        return urlsplit(settings.SITE_URL).scheme or "https"

    def get_domain(self, site=None):
        return urlsplit(settings.SITE_URL).netloc


class PagesSitemap(SiteSitemap):
    changefreq = "weekly"
    NAMES = ["pages:home", "pages:about", "pages:features", "pages:help", "pages:contact", "pages:terms",
             "pages:privacy", "pages:safety", "activities:activity_list", "events:event_list",
             "events:calendar_today", "locations:country_list", "locations:region_list", "locations:city_list",
             "locations:poi_list", "locations:poi_map"]

    def items(self):
        return self.NAMES

    def location(self, item):
        return reverse(item)


class HelpSitemap(SiteSitemap):
    changefreq = "monthly"

    def items(self):
        return helpdocs.visible_to(AnonymousUser())

    def location(self, guide):
        return reverse("pages:help_guide", args=[guide.slug])

    def lastmod(self, guide):
        return guide.updated


class ModelSitemap(SiteSitemap):
    url_name = ""

    def location(self, obj):
        return reverse(self.url_name, args=[obj.slug])

    def lastmod(self, obj):
        return obj.updated_at


def _approved(model):
    return model.objects.filter(approval_status=ApprovalStatus.APPROVED).only("slug", "updated_at").order_by("pk")


class CountrySitemap(ModelSitemap):
    url_name = "locations:country_detail"

    def items(self):
        return _approved(Country)


class RegionSitemap(ModelSitemap):
    url_name = "locations:region_detail"

    def items(self):
        return _approved(Region)


class CitySitemap(ModelSitemap):
    url_name = "locations:city_detail"

    def items(self):
        return _approved(City)


class PlaceSitemap(ModelSitemap):
    url_name = "locations:poi_detail"

    def items(self):
        return _approved(POI)


class ActivitySitemap(ModelSitemap):
    url_name = "activities:activity_detail"

    def items(self):
        return Activity.get_public_activities().only("slug", "updated_at").order_by("pk")


class EventSitemap(ModelSitemap):
    url_name = "events:event_detail"
    changefreq = "weekly"

    def items(self):
        since = timezone.localdate() - timedelta(days=365)
        return _approved(Event).filter(start_date__gte=since)


SITEMAPS = {"pages": PagesSitemap, "help": HelpSitemap, "countries": CountrySitemap, "regions": RegionSitemap,
            "cities": CitySitemap, "places": PlaceSitemap, "activities": ActivitySitemap, "events": EventSitemap}

#: Never crawled: private or per-person areas, fragments and search results.
DISALLOW = ["/trips/", "/public/", "/accounts/", "/staff/", "/admin/", "/approval/", "/notifications/",
            "/bucketlists/", "/search/", "/events/whats-on/", "/report/", "/reviews/", "/notes/"]


def robots_txt(request):
    if getattr(settings, "STAGING", False):
        lines = ["User-agent: *", "Disallow: /"]
    else:
        lines = ["User-agent: *", *(f"Disallow: {path}" for path in DISALLOW), "",
                 f"Sitemap: {settings.SITE_URL.rstrip('/')}{reverse('sitemap')}"]
    response = HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "public, max-age=86400"
    return response
