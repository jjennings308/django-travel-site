# ============================================
# bucketlists/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'bucketlists'

urlpatterns = [
    # Dashboard
    path('', views.bucketlists_dashboard, name='dashboard'),
]