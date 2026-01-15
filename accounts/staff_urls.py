# accounts/staff_urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("admin/accounts/", views.admin_account_list, name="admin_account_list"),
    path("admin/accounts/<int:user_id>/", views.admin_account_detail, name="admin_account_detail"),
    path("admin/accounts/<int:user_id>/toggle-status/", views.admin_toggle_user_status, name="admin_toggle_user_status"),
]
