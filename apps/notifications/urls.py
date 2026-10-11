# notifications/urls.py — mounted at /notifications/ (namespace notifications)
from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.notification_list, name="list"),
    path("unread.json", views.unread_count, name="unread_count"),
    path("<int:pk>/", views.open_notification, name="open"),
    path("read-all/", views.mark_all_read, name="mark_all_read"),
]
