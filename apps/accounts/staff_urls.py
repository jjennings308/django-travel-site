# accounts/staff_urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Account Management
    path("admin/accounts/", views.admin_account_list, name="admin_account_list"),
    path("admin/accounts/<int:user_id>/", views.admin_account_detail, name="admin_account_detail"),
    path("admin/accounts/<int:user_id>/toggle-status/", views.admin_toggle_user_status, name="admin_toggle_user_status"),
    
    # Role Request Management
    path("admin/role-requests/", views.admin_role_requests, name="admin_role_requests"),
    path("admin/role-requests/<int:request_id>/", views.admin_role_request_detail, name="admin_role_request_detail"),
]
