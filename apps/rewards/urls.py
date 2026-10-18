from django.urls import path

from . import views

# The membership pages moved to the travel profile (site roadmap R11); their URLs redirect there
# so old links and bookmarks keep working.
urlpatterns = [
    path('', views.to_travel_profile, name='dashboard'),
    path('memberships/', views.to_travel_profile, name='memberships_list'),
    path('memberships/add/', views.to_travel_profile, name='add_membership'),
    path('memberships/<uuid:membership_id>/', views.to_travel_profile, name='membership_detail'),
    path('memberships/<uuid:membership_id>/edit/', views.to_travel_profile, name='edit_membership'),
    path('programs/', views.programs_browse, name='programs_browse'),
    path('programs/<int:program_id>/', views.program_detail, name='program_detail'),
]
