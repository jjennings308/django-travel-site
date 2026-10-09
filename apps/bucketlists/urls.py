# bucketlists/urls.py
from django.urls import path

from . import views

app_name = "bucketlists"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("add/", views.item_add, name="item_add"),
    path("add/<str:kind>/<int:pk>/", views.quick_add, name="quick_add"),
    path("<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("dates/", views.my_dates, name="dates"),
    path("suggest/", views.suggest, name="suggest"),
    path("<int:pk>/pick-date/", views.pick_date, name="pick_date"),
    path("<int:pk>/link/", views.link_item, name="link_item"),
    path("<int:pk>/plan-trip/", views.plan_trip, name="plan_trip"),
    path("<int:pk>/complete/", views.item_complete, name="item_complete"),
    path("<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("categories/", views.categories, name="categories"),
    path("categories/<int:pk>/", views.category_edit, name="category_edit"),
    path("u/<str:username>/", views.public_list, name="public_list"),
]
