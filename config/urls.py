'''
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
'''
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.trips.views import public_trip_detail


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include(('apps.pages.urls', 'pages'), namespace='pages')),
    path('accounts/', include('apps.accounts.urls')),
    path('rewards/', include(('apps.rewards.urls','rewards'), namespace='rewards')),
    path('bucketlists/', include(('apps.bucketlists.urls', 'bucketlists'), namespace='bucketlists')),
    path('activities/', include(('apps.activities.urls', 'activities'), namespace='activities')),
    path('events/', include(('apps.events.urls', 'events'), namespace='events')),
    path('locations/', include(('apps.locations.urls', 'locations'), namespace='locations')),
    path('trips/', include('apps.trips.urls')),
    path('staff/', include(('apps.accounts.staff_urls', 'staff'), namespace='staff')),  # staff dashboard urls here
    path('staff/trips/', include('apps.trips.staff_urls')),
    # Public, non-detailed trip summary behind a share token. Outside the trips:
    # namespace because every URL there assumes a signed-in reader with a grant.
    path('public/<uuid:token>/', public_trip_detail, name='public_trip'),
    path('approval/', include('apps.approval_system.urls')),
    path("__reload__/", include("django_browser_reload.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)