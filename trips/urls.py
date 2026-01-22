# ============================================
# trips/urls.py
# ============================================
from django.urls import path
from . import views

app_name = 'trips'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),
    path('list/', views.trip_list, name='trip_list'),
    path('stats/', views.trip_stats, name='stats'),
    
    # Trip CRUD
    path('<int:trip_id>/', views.trip_detail, name='trip_detail'),
    path('<int:trip_id>/edit/', views.edit_trip, name='edit_trip'),
    path('<int:trip_id>/delete/', views.delete_trip, name='delete_trip'),
    
    # Adding Trips
    path('add/past/', views.add_past_trip, name='add_past_trip'),
    path('plan/new/', views.plan_new_trip, name='plan_new_trip'),
    
    # Booking
    path('<int:trip_id>/book/', views.book_trip, name='book_trip'),
    path('<int:trip_id>/book/flights/', views.search_flights, name='search_flights'),
    path('<int:trip_id>/book/hotels/', views.search_hotels, name='search_hotels'),
    path('<int:trip_id>/book/add/', views.add_booking, name='add_booking'),
    path('<int:trip_id>/book/confirm/', views.confirm_booking_api, name='confirm_booking_api'),
    
    # Reviews
    path('<int:trip_id>/review/', views.review_trip, name='review_trip'),
    
    # Status Management
    path('<int:trip_id>/status/', views.update_trip_status, name='update_trip_status'),
]
