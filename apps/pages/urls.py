# pages/urls.py
from django.urls import path
from . import account_views, staff, views

app_name = "pages"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("staff/", staff.staff_dashboard, name="staff_dashboard"),
    path("terms/", views.terms, name="terms"),
    path("privacy/", views.privacy, name="privacy"),
    path("safety/", views.safety, name="safety"),
    path("contact/", views.contact, name="contact"),
    path("help/", views.help_page, name="help"),
    path("help/<slug:slug>/", views.help_guide, name="help_guide"),
    path("features/", views.features, name="features"),
    path("account/data/", account_views.my_data, name="my_data"),
    path("dashboard/welcome/hide/", views.welcome_dismiss, name="welcome_dismiss"),
    path("account/data/download/", account_views.data_export, name="data_export"),
 ]
