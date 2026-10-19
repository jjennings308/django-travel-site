# reviews/urls.py
from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    # pk routes first: "<kind>/<slug>/" would otherwise swallow "12/delete/".
    path("<int:pk>/delete/", views.delete, name="delete"),
    path("trip/<int:pk>/rate/", views.trip_rate, name="trip_rate"),
    path("<int:pk>/report/", views.report, name="report"),
    path("<str:kind>/<slug:slug>/", views.for_target, name="for_target"),
    path("<str:kind>/<slug:slug>/write/", views.write, name="write"),
]
