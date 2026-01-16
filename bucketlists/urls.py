# ============================================
# bucketlists/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'bucketlists'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
]