# ============================================
# rewards/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'rewards'

urlpatterns = [
    # Dashboard
    path('', views.rewards_dashboard, name='dashboard'),
    
    # Memberships
    path('memberships/', views.memberships_list, name='memberships_list'),
    path('memberships/add/', views.add_membership, name='add_membership'),
    path('memberships/<uuid:membership_id>/', views.membership_detail, name='membership_detail'),
    path('memberships/<uuid:membership_id>/edit/', views.edit_membership, name='edit_membership'),
    path('memberships/<uuid:membership_id>/delete/', views.delete_membership, name='delete_membership'),
    
    # AJAX actions
    path('memberships/reorder/', views.reorder_memberships, name='reorder_memberships'),
    path('memberships/<uuid:membership_id>/toggle-primary/', views.toggle_primary, name='toggle_primary'),
    
    # Browse programs (public)
    path('programs/', views.programs_browse, name='programs_browse'),
    path('programs/<int:program_id>/', views.program_detail, name='program_detail'),
]
