# ============================================
# activities/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'activities'

urlpatterns = [
    # Dashboard
    path('', views.activities_dashboard, name='dashboard'),
]