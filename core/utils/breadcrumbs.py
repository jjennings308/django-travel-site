# core/utils/breadcrumbs.py
"""
Breadcrumb utilities for consistent navigation across the app.

Usage in views:

from core.utils.breadcrumbs import build_breadcrumbs

def trip_detail(request, trip_id):
    trip = get_object_or_404(Trip, id=trip_id)
    
    context = {
        'trip': trip,
        'breadcrumb_list': build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Trips', 'trips:dashboard'),
            (trip.title, None)  # None = current page
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
                - A URL name string (e.g., 'core:dashboard')
                - A full path (e.g., '/trips/123/')
                - None (for current page - no link)
    
    Returns:
        List of dicts with 'title' and 'url' keys
    
    Examples:
        # Simple breadcrumbs
        build_breadcrumbs([
            ('Home', 'core:home'),
            ('Trips', 'trips:dashboard'),
            ('My Trip', None)
        ])
        
        # With URL kwargs
        build_breadcrumbs([
            ('Home', 'core:home'),
            ('Trips', 'trips:dashboard'),
            ('Trip Detail', ('trips:detail', {'trip_id': 123})),
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
        elif url_info.startswith('/'):
            # Already a path
            url = url_info
        else:
            # URL name without kwargs
            try:
                url = reverse(url_info)
            except Exception:
                # If reverse fails, use as-is (might be external)
                url = url_info
        
        breadcrumb_list.append({
            'title': title,
            'url': url
        })
    
    return breadcrumb_list


# Predefined common breadcrumb patterns
class BreadcrumbPatterns:
    """Common breadcrumb patterns for consistency"""
    
    @staticmethod
    def dashboard_only():
        """Just the dashboard"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard')
        ])
    
    @staticmethod
    def trips_list():
        """Dashboard > Trips"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Trips', None)
        ])
    
    @staticmethod
    def trip_detail(trip):
        """Dashboard > Trips > Trip Name"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Trips', 'trips:dashboard'),
            (trip.title, None)
        ])
    
    @staticmethod
    def trip_edit(trip):
        """Dashboard > Trips > Trip Name > Edit"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Trips', 'trips:dashboard'),
            (trip.title, ('trips:detail', {'trip_id': trip.id})),
            ('Edit', None)
        ])
    
    @staticmethod
    def bucketlist():
        """Dashboard > Bucket List"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Bucket List', None)
        ])
    
    @staticmethod
    def activities_list():
        """Dashboard > Activities"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Activities', None)
        ])
    
    @staticmethod
    def activity_detail(activity):
        """Dashboard > Activities > Activity Name"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Activities', 'activities:dashboard'),
            (activity.name, None)
        ])
    
    @staticmethod
    def locations_dashboard():
        """Dashboard > Locations"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Locations', None)
        ])
        
    @staticmethod
    def locations_list():
        """Dashboard > Activities"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Locations', None)
        ])
    
    @staticmethod
    def countries_list():
        """Dashboard > Locations > Countries"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Locations', 'locations:dashboard'),
            ('Countries', None)
        ])
    
    @staticmethod
    def country_add():
        """Dashboard > Locations > Countries > Add Country"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Locations', 'locations:dashboard'),
            ('Countries', 'locations:country_list'),
            ('Add Country', None)
        ])
    
    @staticmethod
    def country_detail(country):
        """Dashboard > Locations > Countries > Country Name"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Locations', 'locations:dashboard'),
            ('Countries', 'locations:country_list'),
            (country.name, None)
        ])
    
    @staticmethod
    def country_edit(country):
        """Dashboard > Locations > Countries > Country Name > Edit"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Locations', 'locations:dashboard'),
            ('Countries', 'locations:country_list'),
            (country.name, ('locations:country_detail', {'slug': country.slug})),
            ('Edit', None)
        ])
    
    @staticmethod
    def events_list():
        """Dashboard > Events"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Events', None)
        ])
    
    @staticmethod
    def event_detail(event):
        """Dashboard > Events > Event Name"""
        return build_breadcrumbs([
            ('Dashboard', 'core:dashboard'),
            ('Events', 'events:dashboard'),
            (event.title, None)
        ])


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
            ('Dashboard', 'core:dashboard'),
            ('Trips', 'trips:dashboard'),
            (trip.title, ('trips:detail', {'trip_id': trip.id})),
            ('Book Flights', None)
        ])
    }
    return render(request, 'trips/book_flights.html', context)
"""
