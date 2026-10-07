# locations/urls.py
from django.urls import path
from . import views

app_name = 'locations'

urlpatterns = [
    # Dashboard
    path('', views.location_dashboard, name='dashboard'),
    
    # Countries
    path('countries/', views.country_list, name='country_list'),
    path('countries/add/', views.country_add, name='country_add'),
    path('countries/<slug:slug>/', views.country_detail, name='country_detail'),
    path('countries/<slug:slug>/edit/', views.country_edit, name='country_edit'),
    
    # Regions
    path('regions/', views.region_list, name='region_list'),
    path('regions/add/', views.region_add, name='region_add'),
    path('regions/<slug:slug>/', views.region_detail, name='region_detail'),
    
    # Cities
    path('cities/', views.city_list, name='city_list'),
    path('cities/add/', views.city_add, name='city_add'),
    path('cities/<slug:slug>/', views.city_detail, name='city_detail'),
    
    # POIs
    path('pois/', views.poi_list, name='poi_list'),
    path('pois/add/', views.poi_add, name='poi_add'),
    path('pois/<slug:slug>/', views.poi_detail, name='poi_detail'),
    
    # AJAX endpoints
    path('api/countries/<int:country_id>/regions/', views.get_regions_for_country, name='get_regions'),
    path('api/regions/<int:region_id>/cities/', views.get_cities_for_region, name='get_cities_region'),
    path('api/countries/<int:country_id>/cities/', views.get_cities_for_country, name='get_cities_country'),
]
