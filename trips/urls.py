# ============================================
# trips/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'trips'

urlpatterns = [
    # Dashboard
    path('', views.trips_dashboard, name='dashboard'),
]