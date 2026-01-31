# approval_system/urls.py

from django.urls import path
from . import views

app_name = 'approval_system'

urlpatterns = [
    # Main dashboard
    path('', views.approval_dashboard, name='dashboard'),
    
    # Queue management
    path('queue/<slug:queue_slug>/', views.queue_detail, name='queue_detail'),
    
    # Review specific item
    path('review/<int:content_type_id>/<int:object_id>/', 
         views.review_item, name='review_item'),
    
    # Bulk actions
    path('bulk-action/', views.bulk_action, name='bulk_action'),
    
    # User submissions
    path('my-submissions/', views.my_submissions, name='my_submissions'),
    
    # Statistics
    path('stats/', views.approval_stats, name='stats'),
    
    # API endpoints
    path('api/pending-counts/', views.api_pending_counts, name='api_pending_counts'),
    path('api/stats/', views.api_review_stats, name='api_review_stats'),
]
