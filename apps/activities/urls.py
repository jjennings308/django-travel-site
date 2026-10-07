# activities/urls.py
from django.urls import path
from . import views

app_name = 'activities'

urlpatterns = [
    # Public views
    path('', views.activity_list, name='activity_list'),
    
    # User activity management
    path('my/activities/', views.my_activities, name='my_activities'),
    path('my/bookmarks/', views.my_bookmarks, name='my_bookmarks'),
    
    # Create/Edit
    path('add/', views.activity_add, name='activity_add'),
    path('quick-add/', views.activity_quick_add, name='activity_quick_add'),
    path('<slug:slug>/', views.activity_detail, name='activity_detail'),
    path('<slug:slug>/edit/', views.activity_edit, name='activity_edit'),
    path('<slug:slug>/delete/', views.activity_delete, name='activity_delete'),
    
    # Approval workflow
    path('<slug:slug>/submit-public/', views.activity_submit_for_public, name='activity_submit_for_public'),
    path('<slug:slug>/make-private/', views.activity_make_private, name='activity_make_private'),
    
    # Bookmarks
    path('<slug:slug>/bookmark/', views.activity_bookmark, name='activity_bookmark'),
    path('<slug:slug>/unbookmark/', views.activity_unbookmark, name='activity_unbookmark'),
]
