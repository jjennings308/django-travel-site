# events/urls.py
from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("mine/", views.my_events, name="my_events"),
    path("add/", views.event_add, name="event_add"),
    path("<slug:slug>/", views.event_detail, name="event_detail"),
    path("<slug:slug>/edit/", views.event_edit, name="event_edit"),
    path("<slug:slug>/delete/", views.event_delete, name="event_delete"),
    path("<slug:slug>/link-city/", views.event_link_city, name="event_link_city"),
]
