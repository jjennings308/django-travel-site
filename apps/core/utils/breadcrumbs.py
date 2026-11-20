"""
Breadcrumb utilities for consistent navigation across the app.

Usage in views:

from apps.core.utils.breadcrumbs import build_breadcrumbs

def trip_detail(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id)

    context = {
        'trip': trip,
        'breadcrumb_list': build_breadcrumbs([
            ('Home', 'pages:dashboard'),
            ('Trips', 'trips:trip_list'),
            (trip.name, None)  # None = current page
        ])
    }
    return render(request, 'trips/trip_detail.html', context)
"""

from django.urls import reverse


def build_breadcrumbs(crumbs):
    """
    Build a breadcrumb list from simple tuples.

    Args:
        crumbs: List of tuples (title, url_name_or_path)
                url_name_or_path can be:
                - A URL name string (e.g., 'pages:dashboard')
                - A full path (e.g., '/trips/123/')
                - None (for current page - no link)

    Returns:
        List of dicts with 'title' and 'url' keys

    Examples:
        # Simple breadcrumbs
        build_breadcrumbs([
            ('Home', 'pages:home'),
            ('Trips', 'trips:trip_list'),
            ('My Trip', None)
        ])

        # With URL kwargs
        build_breadcrumbs([
            ('Home', 'pages:home'),
            ('Trips', 'trips:trip_list'),
            ('Trip Detail', ('trips:trip_detail', {'pk': 123})),
            ('Edit', None)
        ])
    """
    breadcrumb_list = []

    for crumb in crumbs:
        title = crumb[0]
        url_info = crumb[1]

        # Determine URL
        if url_info is None:
            # Current page - no URL
            url = None
        elif isinstance(url_info, tuple):
            # URL name with kwargs: ('url:name', {'arg': value})
            url_name, kwargs = url_info
            url = reverse(url_name, kwargs=kwargs)
        elif url_info.startswith("/"):
            # Already a path
            url = url_info
        else:
            # URL name without kwargs
            try:
                url = reverse(url_info)
            except Exception:
                # If reverse fails, use as-is (might be external)
                url = url_info

        breadcrumb_list.append({"title": title, "url": url})

    return breadcrumb_list


# Predefined common breadcrumb patterns
class BreadcrumbPatterns:
    """Common breadcrumb patterns for consistency"""

    @staticmethod
    def dashboard_only():
        """Just the dashboard"""
        return build_breadcrumbs([("Home", "pages:dashboard")])

    @staticmethod
    def trips_list():
        """Home > Trips"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Trips", None)])

    @staticmethod
    def trip_detail(trip):
        """Home > Trips > Trip Name"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Trips", "trips:trip_list"), (trip.name, None)])

    @staticmethod
    def trip_edit(trip):
        """Home > Trips > Trip Name > Edit"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Trips", "trips:trip_list"),
                (trip.name, ("trips:trip_detail", {"pk": trip.pk})),
                ("Edit", None),
            ]
        )

    @staticmethod
    def bucketlist():
        """Home > Bucket List"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Bucket List", None)])

    @staticmethod
    def activities_list():
        """Home > Activities"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Activities", None)])

    @staticmethod
    def activity_detail(activity):
        """Home > Activities > Activity Name"""
        return build_breadcrumbs(
            [("Home", "pages:dashboard"), ("Activities", "activities:dashboard"), (activity.name, None)]
        )

    @staticmethod
    def locations_dashboard():
        """Home > Locations"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Locations", None)])

    @staticmethod
    def countries_list():
        """Home > Locations > Countries"""
        return build_breadcrumbs(
            [("Home", "pages:dashboard"), ("Locations", "locations:dashboard"), ("Countries", None)]
        )

    @staticmethod
    def country_add():
        """Home > Locations > Countries > Add Country"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Countries", "locations:country_list"),
                ("Add Country", None),
            ]
        )

    @staticmethod
    def country_detail(country):
        """Home > Locations > Countries > Country Name"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Countries", "locations:country_list"),
                (country.name, None),
            ]
        )

    @staticmethod
    def country_edit(country):
        """Home > Locations > Countries > Country Name > Edit"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Countries", "locations:country_list"),
                (country.name, ("locations:country_detail", {"slug": country.slug})),
                ("Edit", None),
            ]
        )

    @staticmethod
    def regions_list():
        """Home > Locations > Regions"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Locations", "locations:dashboard"), ("Regions", None)])

    @staticmethod
    def region_add():
        """Home > Locations > Regions > Add Region"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Regions", "locations:region_list"),
                ("Add Region", None),
            ]
        )

    @staticmethod
    def region_detail(region):
        """Home > Locations > Regions > Region Name"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Regions", "locations:region_list"),
                (region.name, None),
            ]
        )

    @staticmethod
    def region_edit(region):
        """Home > Locations > Regions > Region Name > Edit"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Regions", "locations:region_list"),
                (region.name, ("locations:region_detail", {"slug": region.slug})),
                ("Edit", None),
            ]
        )

    @staticmethod
    def cities_list():
        """Home > Locations > Cities"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Locations", "locations:dashboard"), ("Cities", None)])

    @staticmethod
    def city_add():
        """Home > Locations > Cities > Add City"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Cities", "locations:city_list"),
                ("Add City", None),
            ]
        )

    @staticmethod
    def city_detail(city):
        """Home > Locations > Cities > City Name"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Cities", "locations:city_list"),
                (city.name, None),
            ]
        )

    @staticmethod
    def city_edit(city):
        """Home > Locations > Cities > City Name > Edit"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Cities", "locations:city_list"),
                (city.name, ("locations:city_detail", {"slug": city.slug})),
                ("Edit", None),
            ]
        )

    @staticmethod
    def pois_list():
        """Home > Locations > Places"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Locations", "locations:dashboard"), ("Places", None)])

    @staticmethod
    def poi_add():
        """Home > Locations > Places > Add a place"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Places", "locations:poi_list"),
                ("Add a place", None),
            ]
        )

    @staticmethod
    def poi_detail(poi):
        """Home > Locations > Places > Place name"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Places", "locations:poi_list"),
                (poi.name, None),
            ]
        )

    @staticmethod
    def poi_edit(poi):
        """Home > Locations > Places > Place name > Edit"""
        return build_breadcrumbs(
            [
                ("Home", "pages:dashboard"),
                ("Locations", "locations:dashboard"),
                ("Places", "locations:poi_list"),
                (poi.name, ("locations:poi_detail", {"slug": poi.slug})),
                ("Edit", None),
            ]
        )

    @staticmethod
    def events_list():
        """Home > Events"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Events", None)])

    @staticmethod
    def event_detail(event):
        """Home > Events > Event Name"""
        return build_breadcrumbs([("Home", "pages:dashboard"), ("Events", "events:event_list"), (event.title, None)])


# Example usage in views:
"""
# Simple approach - build manually
def trip_detail(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id)
    context = {
        'trip': trip,
        'breadcrumb_list': BreadcrumbPatterns.trip_detail(trip)
    }
    return render(request, 'trips/trip_detail.html', context)

# Or custom breadcrumbs
def trip_booking(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id)
    context = {
        'trip': trip,
        'breadcrumb_list': build_breadcrumbs([
            ('Home', 'pages:dashboard'),
            ('Trips', 'trips:trip_list'),
            (trip.name, ('trips:trip_detail', {'pk': trip.pk})),
            ('Book Flights', None)
        ])
    }
    return render(request, 'trips/book_flights.html', context)
"""
