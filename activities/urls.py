# ============================================
# activities/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'activities'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
]