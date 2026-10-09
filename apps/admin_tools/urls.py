# admin_tools/urls.py — CSV import/export, mounted at /staff/import/ (namespace admin_tools)
from django.urls import path

from . import views

app_name = "admin_tools"

urlpatterns = [
    path("", views.import_start, name="import"),
    path("preview/", views.import_preview, name="import_preview"),
    path("cancel/", views.import_cancel, name="import_cancel"),
    path("template/<str:kind>.csv", views.import_template, name="import_template"),
    path("export/<str:kind>.csv", views.export, name="export"),
]
