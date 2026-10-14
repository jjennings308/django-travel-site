# bucketlists/urls.py
from django.urls import path

from . import photos, views

app_name = "bucketlists"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("add/", views.item_add, name="item_add"),
    path("add/<str:kind>/<int:pk>/", views.quick_add, name="quick_add"),
    path("<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("dates/", views.my_dates, name="dates"),
    path("adventures/", views.adventures, name="adventures"),
    path("suggest/", views.suggest, name="suggest"),
    path("<int:pk>/pick-date/", views.pick_date, name="pick_date"),
    path("trip/<int:trip_pk>/done/", views.trip_done, name="trip_done"),
    path("trip/<int:trip_pk>/", views.trip_goals, name="trip_goals"),
    path("trip/<int:trip_pk>/map-places.json", views.trip_map_places, name="trip_map_places"),
    path("<int:pk>/add-to-trip/", views.add_to_trip, name="add_to_trip"),
    path("<int:pk>/remove-from-trip/", views.remove_from_trip, name="remove_from_trip"),
    path("<int:pk>/link/", views.link_item, name="link_item"),
    path("<int:pk>/plan-trip/", views.plan_trip, name="plan_trip"),
    path("<int:pk>/complete/", views.item_complete, name="item_complete"),
    path("<int:pk>/photos/", photos.item_photos, name="item_photos"),
    path("<int:pk>/photos/<int:media_pk>/delete/", photos.item_photo_delete, name="item_photo_delete"),
    path("albums/", photos.albums, name="albums"),
    path("albums/new/", photos.album_new, name="album_new"),
    path("albums/<int:pk>/", photos.album_detail, name="album_detail"),
    path("albums/<int:pk>/edit/", photos.album_edit, name="album_edit"),
    path("albums/<int:pk>/add/", photos.album_pick, name="album_pick"),
    path("albums/<int:pk>/delete/", photos.album_delete, name="album_delete"),
    path("albums/<int:pk>/photos/<int:media_pk>/remove/", photos.album_remove, name="album_remove"),
    path("albums/<int:pk>/photos/<int:media_pk>/cover/", photos.album_cover, name="album_cover"),
    path("<int:pk>/delete/", views.item_delete, name="item_delete"),
    path("categories/", views.categories, name="categories"),
    path("categories/<int:pk>/", views.category_edit, name="category_edit"),
    path("u/<str:username>/", views.public_list, name="public_list"),
]
