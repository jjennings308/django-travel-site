from django.urls import path

from . import views

app_name = "catalogue_notes"

urlpatterns = [
    path("<int:pk>/edit/", views.edit, name="edit"),
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("<int:pk>/report/", views.report, name="report"),
    path("<str:kind>/<slug:slug>/", views.for_target, name="for_target"),
    path("<str:kind>/<slug:slug>/add/", views.add, name="add"),
]
