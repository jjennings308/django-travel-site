# ============================================
# events/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'events'

urlpatterns = [
    # Dashboard
    path('', views.events_dashboard, name='dashboard'),
]