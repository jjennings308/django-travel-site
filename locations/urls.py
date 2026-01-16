# ============================================
# locations/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'locations'

urlpatterns = [
    # Dashboard
    path('', views.locations_dashboard, name='dashboard'),
]