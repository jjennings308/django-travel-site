# pages/urls.py
from django.urls import path
from . import staff, views

app_name = "pages"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("staff/", staff.staff_dashboard, name="staff_dashboard"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("safety/", views.safety, name="safety"),
 ]
