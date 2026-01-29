# locations/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Prefetch
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import Country, Region, City, POI, LocationStatus, CapitalType
from media_app.models import Media
from approval_system.models import ApprovalStatus
from accounts.models import User
from core.utils.breadcrumbs import BreadcrumbPatterns



# ============================================================================
# DASHBOARD VIEWS
# ============================================================================

@login_required
def location_dashboard(request):
    """Main dashboard for location management"""
    
    # Get counts by status
    countries_pending = Country.objects.filter(approval_status=ApprovalStatus.PENDING).count()
    regions_pending = Region.objects.filter(approval_status=ApprovalStatus.PENDING).count()
    cities_pending = City.objects.filter(approval_status=ApprovalStatus.PENDING).count()
    pois_pending = POI.objects.filter(approval_status=ApprovalStatus.PENDING).count()
    
    countries_approved = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).count()
    regions_approved = Region.objects.filter(approval_status=ApprovalStatus.APPROVED).count()
    cities_approved = City.objects.filter(approval_status=ApprovalStatus.APPROVED).count()
    pois_approved = POI.objects.filter(approval_status=ApprovalStatus.APPROVED).count()
    
    # Recent submissions
    recent_countries = Country.objects.filter(
        submitted_by=request.user
    ).order_by('-submitted_at')[:5]
    
    recent_regions = Region.objects.filter(
        submitted_by=request.user
    ).order_by('-submitted_at')[:5]
    
    recent_cities = City.objects.filter(
        submitted_by=request.user
    ).order_by('-submitted_at')[:5]
    
    recent_pois = POI.objects.filter(
        submitted_by=request.user
    ).order_by('-submitted_at')[:5]
    
    context = {
        'countries_pending': countries_pending,
        'regions_pending': regions_pending,
        'cities_pending': cities_pending,
        'pois_pending': pois_pending,
        'countries_approved': countries_approved,
        'regions_approved': regions_approved,
        'cities_approved': cities_approved,
        'pois_approved': pois_approved,
        'recent_countries': recent_countries,
        'recent_regions': recent_regions,
        'recent_cities': recent_cities,
        'recent_pois': recent_pois,
        'breadcrumb_list': BreadcrumbPatterns.locations_dashboard(),
    }
    
    return render(request, 'locations/dashboard.html', context)


# ============================================================================
# COUNTRY VIEWS
# ============================================================================

@login_required
def country_list(request):
    """List all countries with filtering"""
    
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('q', '')
    continent_filter = request.GET.get('continent', '')
    
    countries = Country.objects.select_related('featured_media').all()
    
    # Apply filters
    if status_filter != 'all':
        countries = countries.filter(approval_status=status_filter)
    
    if search_query:
        countries = countries.filter(
            Q(name__icontains=search_query) |
            Q(iso_code__icontains=search_query) |
            Q(iso3_code__icontains=search_query)
        )
    
    if continent_filter:
        countries = countries.filter(continent=continent_filter)
    
    countries = countries.order_by('name')
    
    # Pagination
    paginator = Paginator(countries, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'continent_filter': continent_filter,
        'continents': [choice[0] for choice in Country._meta.get_field('continent').choices],
        'breadcrumb_list': BreadcrumbPatterns.countries_list(),
    }
    
    return render(request, 'locations/country_list.html', context)


@login_required
def country_detail(request, slug):
    """View country details with regions and cities"""
    
    country = get_object_or_404(
        Country.objects.select_related('featured_media')
        .prefetch_related('regions', 'cities'),
        slug=slug
    )
    
    # Get regions with city count
    regions = country.regions.annotate(
        total_cities=Count('cities')
    ).order_by('name')
    
    # Get major cities
    cities = country.cities.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('region', 'featured_media').order_by('-population')[:10]
    
    # Get featured POIs
    featured_pois = POI.objects.filter(
        city__country=country,
        approval_status=ApprovalStatus.APPROVED
    ).select_related('city', 'featured_media').order_by('-visitor_count')[:8]
    
    context = {
        'country': country,
        'regions': regions,
        'cities': cities,
        'featured_pois': featured_pois,
        'breadcrumb_list': BreadcrumbPatterns.country_detail(country),
    }
    
    return render(request, 'locations/country_detail.html', context)


@login_required
def country_add(request):
    """Add a new country for approval"""
    
    if request.method == 'POST':
        # Get form data
        name = request.POST.get('name')
        iso_code = request.POST.get('iso_code', '').upper()
        iso3_code = request.POST.get('iso3_code', '').upper()
        continent = request.POST.get('continent')
        description = request.POST.get('description', '')
        travel_tips = request.POST.get('travel_tips', '')
        currency_code = request.POST.get('currency_code', '')
        currency_name = request.POST.get('currency_name', '')
        phone_code = request.POST.get('phone_code', '')
        visa_info = request.POST.get('visa_info', '')
        visa_required = request.POST.get('visa_required') == 'on'
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        featured_media_id = request.POST.get('featured_media_id')
        
        # Validation
        if not all([name, iso_code, iso3_code, continent]):
            messages.error(request, 'Please fill in all required fields.')
            return redirect('locations:country_add')
        
        # Check for duplicates
        if Country.objects.filter(Q(name=name) | Q(iso_code=iso_code) | Q(iso3_code=iso3_code)).exists():
            messages.error(request, 'A country with this name or code already exists.')
            return redirect('locations:country_add')
        
        # Create country
        country = Country.objects.create(
            name=name,
            iso_code=iso_code,
            iso3_code=iso3_code,
            continent=continent,
            description=description,
            travel_tips=travel_tips,
            currency_code=currency_code,
            currency_name=currency_name,
            phone_code=phone_code,
            visa_info=visa_info,
            visa_required=visa_required,
            latitude=latitude if latitude else None,
            longitude=longitude if longitude else None,
            submitted_by=request.user,
            approval_status=ApprovalStatus.PENDING
        )
        
        # Attach featured media if provided
        if featured_media_id:
            try:
                media = Media.objects.get(id=featured_media_id, uploaded_by=request.user)
                country.featured_media = media
                country.save()
            except Media.DoesNotExist:
                pass
        
        # Submit for review
        country.submit_for_review(request.user)
        
        messages.success(request, f'Country "{name}" submitted for approval!')
        return redirect('locations:country_detail', slug=country.slug)
    
    # GET request - show form
    continents = [choice for choice in Country._meta.get_field('continent').choices]
    user_media = Media.objects.filter(uploaded_by=request.user, media_type='image').order_by('-created_at')[:20]
    
    context = {
        'continents': continents,
        'user_media': user_media,
        'breadcrumb_list': BreadcrumbPatterns.country_add(),
    }
    
    return render(request, 'locations/country_add.html', context)


@login_required
def country_edit(request, slug):
    """Edit an existing country"""
    
    country = get_object_or_404(Country, slug=slug)
    
    # Check permissions
    if not request.user.is_staff and country.submitted_by != request.user:
        messages.error(request, 'You do not have permission to edit this country.')
        return redirect('locations:country_detail', slug=slug)
    
    if request.method == 'POST':
        # Update fields
        country.name = request.POST.get('name')
        country.iso_code = request.POST.get('iso_code', '').upper()
        country.iso3_code = request.POST.get('iso3_code', '').upper()
        country.continent = request.POST.get('continent')
        country.description = request.POST.get('description', '')
        country.travel_tips = request.POST.get('travel_tips', '')
        country.currency_code = request.POST.get('currency_code', '')
        country.currency_name = request.POST.get('currency_name', '')
        country.phone_code = request.POST.get('phone_code', '')
        country.visa_info = request.POST.get('visa_info', '')
        country.visa_required = request.POST.get('visa_required') == 'on'
        
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        country.latitude = latitude if latitude else None
        country.longitude = longitude if longitude else None
        
        # Update featured media
        featured_media_id = request.POST.get('featured_media_id')
        if featured_media_id:
            try:
                media = Media.objects.get(id=featured_media_id)
                country.featured_media = media
            except Media.DoesNotExist:
                pass
        
        country.save()
        messages.success(request, f'Country "{country.name}" updated successfully!')
        return redirect('locations:country_detail', slug=country.slug)
    
    continents = [choice for choice in Country._meta.get_field('continent').choices]
    user_media = Media.objects.filter(uploaded_by=request.user, media_type='image').order_by('-created_at')[:20]
    
    context = {
        'country': country,
        'continents': continents,
        'user_media': user_media,
    }
    
    return render(request, 'locations/country_edit.html', context)


# ============================================================================
# REGION VIEWS
# ============================================================================

@login_required
def region_list(request):
    """List all regions with filtering"""
    
    status_filter = request.GET.get('status', 'all')
    country_id = request.GET.get('country')
    search_query = request.GET.get('q', '')
    
    regions = Region.objects.select_related('country', 'featured_media').all()
    
    # Apply filters
    if status_filter != 'all':
        regions = regions.filter(approval_status=status_filter)
    
    if country_id:
        regions = regions.filter(country_id=country_id)
    
    if search_query:
        regions = regions.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(country__name__icontains=search_query)
        )
    
    regions = regions.order_by('country__name', 'name')
    
    # Pagination
    paginator = Paginator(regions, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by('name')
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'countries': countries,
        'selected_country': country_id,
        'breadcrumb_list': BreadcrumbPatterns.regions_list
    }
    
    return render(request, 'locations/region_list.html', context)


@login_required
def region_detail(request, slug):
    """View region details"""
    
    region = get_object_or_404(
        Region.objects.select_related('country', 'featured_media')
        .prefetch_related('cities'),
        slug=slug
    )
    
    # Get cities in this region
    cities = region.cities.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('featured_media').order_by('-population')
    
    context = {
        'region': region,
        'cities': cities,
        'breadcrumb_list': BreadcrumbPatterns.region_detail(region)
    }
    
    return render(request, 'locations/region_detail.html', context)


@login_required
def region_add(request):
    """Add a new region for approval"""
    
    if request.method == 'POST':
        name = request.POST.get('name')
        country_id = request.POST.get('country')
        code = request.POST.get('code', '').upper()
        description = request.POST.get('description', '')
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        featured_media_id = request.POST.get('featured_media_id')
        
        if not all([name, country_id]):
            messages.error(request, 'Please fill in all required fields.')
            return redirect('locations:region_add')
        
        try:
            country = Country.objects.get(id=country_id)
        except Country.DoesNotExist:
            messages.error(request, 'Invalid country selected.')
            return redirect('locations:region_add')
        
        # Check for duplicates
        if Region.objects.filter(country=country, name=name).exists():
            messages.error(request, 'This region already exists in the selected country.')
            return redirect('locations:region_add')
        
        region = Region.objects.create(
            country=country,
            name=name,
            code=code,
            description=description,
            latitude=latitude if latitude else None,
            longitude=longitude if longitude else None,
            submitted_by=request.user,
            approval_status=ApprovalStatus.PENDING
        )
        
        # Attach featured media
        if featured_media_id:
            try:
                media = Media.objects.get(id=featured_media_id, uploaded_by=request.user)
                region.featured_media = media
                region.save()
            except Media.DoesNotExist:
                pass
        
        region.submit_for_review(request.user)
        
        messages.success(request, f'Region "{name}" submitted for approval!')
        return redirect('locations:region_detail', slug=region.slug)
    
    countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by('name')
    user_media = Media.objects.filter(uploaded_by=request.user, media_type='image').order_by('-created_at')[:20]
    
    context = {
        'countries': countries,
        'user_media': user_media,
        'breadcrumb_list': BreadcrumbPatterns.region_add
    }
    
    return render(request, 'locations/region_add.html', context)


# ============================================================================
# CITY VIEWS
# ============================================================================

@login_required
def city_list(request):
    """List all cities with filtering"""
    
    status_filter = request.GET.get('status', 'all')
    country_id = request.GET.get('country')
    region_id = request.GET.get('region')
    search_query = request.GET.get('q', '')
    capital_only = request.GET.get('capital') == 'true'
    
    cities = City.objects.select_related('country', 'region', 'featured_media').all()
    
    # Apply filters
    if status_filter != 'all':
        cities = cities.filter(approval_status=status_filter)
    
    if country_id:
        cities = cities.filter(country_id=country_id)
    
    if region_id:
        cities = cities.filter(region_id=region_id)
    
    if capital_only:
        cities = cities.filter(is_capital=True)
    
    if search_query:
        cities = cities.filter(
            Q(name__icontains=search_query) |
            Q(country__name__icontains=search_query) |
            Q(region__name__icontains=search_query)
        )
    
    cities = cities.order_by('country__name', 'name')
    
    # Pagination
    paginator = Paginator(cities, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by('name')
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'countries': countries,
        'selected_country': country_id,
        'capital_only': capital_only,
        'breadcrumb_list': BreadcrumbPatterns.cities_list
    }
    
    return render(request, 'locations/city_list.html', context)


@login_required
def city_detail(request, slug):
    """View city details"""
    
    city = get_object_or_404(
        City.objects.select_related('country', 'region', 'featured_media')
        .prefetch_related('pois'),
        slug=slug
    )
    
    # Get POIs in this city
    pois = city.pois.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('featured_media').order_by('-visitor_count')
    
    context = {
        'city': city,
        'pois': pois,
        'breadcrumb_list': BreadcrumbPatterns.city_detail(city)
    }
    
    return render(request, 'locations/city_detail.html', context)


@login_required
def city_add(request):
    """Add a new city for approval"""
    
    if request.method == 'POST':
        name = request.POST.get('name')
        country_id = request.POST.get('country')
        region_id = request.POST.get('region')
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        description = request.POST.get('description', '')
        population = request.POST.get('population')
        timezone_str = request.POST.get('timezone', '')
        best_time = request.POST.get('best_time_to_visit', '')
        budget = request.POST.get('average_daily_budget')
        capital_type = request.POST.get('capital_type')
        elevation = request.POST.get('elevation_m')
        featured_media_id = request.POST.get('featured_media_id')
        
        if not all([name, country_id, latitude, longitude]):
            messages.error(request, 'Please fill in all required fields.')
            return redirect('locations:city_add')
        
        try:
            country = Country.objects.get(id=country_id)
        except Country.DoesNotExist:
            messages.error(request, 'Invalid country selected.')
            return redirect('locations:city_add')
        
        region = None
        if region_id:
            try:
                region = Region.objects.get(id=region_id, country=country)
            except Region.DoesNotExist:
                pass
        
        # Check for duplicates
        if City.objects.filter(country=country, name=name).exists():
            messages.error(request, 'This city already exists in the selected country.')
            return redirect('locations:city_add')
        
        city = City.objects.create(
            country=country,
            region=region,
            name=name,
            latitude=latitude,
            longitude=longitude,
            description=description,
            population=population if population else None,
            timezone=timezone_str,
            best_time_to_visit=best_time,
            average_daily_budget=budget if budget else None,
            capital_type=capital_type if capital_type else None,
            elevation_m=elevation if elevation else None,
            submitted_by=request.user,
            approval_status=ApprovalStatus.PENDING
        )
        
        # Attach featured media
        if featured_media_id:
            try:
                media = Media.objects.get(id=featured_media_id, uploaded_by=request.user)
                city.featured_media = media
                city.save()
            except Media.DoesNotExist:
                pass
        
        city.submit_for_review(request.user)
        
        messages.success(request, f'City "{name}" submitted for approval!')
        return redirect('locations:city_detail', slug=city.slug)
    
    countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by('name')
    capital_types = CapitalType.choices
    user_media = Media.objects.filter(uploaded_by=request.user, media_type='image').order_by('-created_at')[:20]
    
    context = {
        'countries': countries,
        'capital_types': capital_types,
        'user_media': user_media,
        'breadcrumb_list': BreadcrumbPatterns.city_add
    }
    
    return render(request, 'locations/city_add.html', context)


# ============================================================================
# POI VIEWS
# ============================================================================

@login_required
def poi_list(request):
    """List all POIs with filtering"""
    
    status_filter = request.GET.get('status', 'all')
    city_id = request.GET.get('city')
    poi_type = request.GET.get('type')
    search_query = request.GET.get('q', '')
    
    pois = POI.objects.select_related('city', 'city__country', 'featured_media').all()
    
    # Apply filters
    if status_filter != 'all':
        pois = pois.filter(approval_status=status_filter)
    
    if city_id:
        pois = pois.filter(city_id=city_id)
    
    if poi_type:
        pois = pois.filter(poi_type=poi_type)
    
    if search_query:
        pois = pois.filter(
            Q(name__icontains=search_query) |
            Q(city__name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    pois = pois.order_by('city__country__name', 'city__name', 'name')
    
    # Pagination
    paginator = Paginator(pois, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    poi_types = POI.POI_TYPES
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'poi_types': poi_types,
        'selected_type': poi_type,
        'breadcrumb_list': BreadcrumbPatterns.pois_list
    }
    
    return render(request, 'locations/poi_list.html', context)


@login_required
def poi_detail(request, slug):
    """View POI details"""
    
    poi = get_object_or_404(
        POI.objects.select_related('city', 'city__country', 'city__region', 'featured_media'),
        slug=slug
    )
        
    context = {
        'poi': poi,
        'breadcrumb_list': BreadcrumbPatterns.poi_detail(poi)
    }
    
    return render(request, 'locations/poi_detail.html', context)


@login_required
def poi_add(request):
    """Add a new POI for approval"""
    
    if request.method == 'POST':
        name = request.POST.get('name')
        city_id = request.POST.get('city')
        poi_type = request.POST.get('poi_type')
        latitude = request.POST.get('latitude')
        longitude = request.POST.get('longitude')
        description = request.POST.get('description', '')
        address = request.POST.get('address', '')
        website = request.POST.get('website', '')
        phone = request.POST.get('phone', '')
        entry_fee = request.POST.get('entry_fee')
        entry_fee_currency = request.POST.get('entry_fee_currency', '')
        typical_duration = request.POST.get('typical_duration')
        elevation = request.POST.get('elevation_m')
        wheelchair_accessible = request.POST.get('wheelchair_accessible') == 'on'
        parking_available = request.POST.get('parking_available') == 'on'
        featured_media_id = request.POST.get('featured_media_id')
        
        if not all([name, city_id, poi_type, latitude, longitude]):
            messages.error(request, 'Please fill in all required fields.')
            return redirect('locations:poi_add')
        
        try:
            city = City.objects.get(id=city_id)
        except City.DoesNotExist:
            messages.error(request, 'Invalid city selected.')
            return redirect('locations:poi_add')
        
        poi = POI.objects.create(
            city=city,
            name=name,
            poi_type=poi_type,
            latitude=latitude,
            longitude=longitude,
            description=description,
            address=address,
            website=website,
            phone=phone,
            entry_fee=entry_fee if entry_fee else None,
            entry_fee_currency=entry_fee_currency,
            typical_duration=typical_duration if typical_duration else None,
            elevation_m=elevation if elevation else None,
            wheelchair_accessible=wheelchair_accessible,
            parking_available=parking_available,
            submitted_by=request.user,
            approval_status=ApprovalStatus.PENDING
        )
        
        # Attach featured media
        if featured_media_id:
            try:
                media = Media.objects.get(id=featured_media_id, uploaded_by=request.user)
                poi.featured_media = media
                poi.save()
            except Media.DoesNotExist:
                pass
        
        poi.submit_for_review(request.user)
        
        messages.success(request, f'POI "{name}" submitted for approval!')
        return redirect('locations:poi_detail', slug=poi.slug)
    
    # Get cities grouped by country
    cities = City.objects.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('country').order_by('country__name', 'name')
    
    poi_types = POI.POI_TYPES
    user_media = Media.objects.filter(
        uploaded_by=request.user,
        media_type__in=['image', 'video']
    ).order_by('-created_at')[:20]
    
    context = {
        'cities': cities,
        'poi_types': poi_types,
        'user_media': user_media,
        'breadcrumb_list': BreadcrumbPatterns.poi_add
    }
    
    return render(request, 'locations/poi_add.html', context)


# ============================================================================
# AJAX/API VIEWS
# ============================================================================

@login_required
@require_http_methods(["GET"])
def get_regions_for_country(request, country_id):
    """Get regions for a specific country (AJAX)"""
    
    regions = Region.objects.filter(
        country_id=country_id,
        approval_status=ApprovalStatus.APPROVED
    ).values('id', 'name', 'code').order_by('name')
    
    return JsonResponse({'regions': list(regions)})


@login_required
@require_http_methods(["GET"])
def get_cities_for_region(request, region_id):
    """Get cities for a specific region (AJAX)"""
    
    cities = City.objects.filter(
        region_id=region_id,
        approval_status=ApprovalStatus.APPROVED
    ).values('id', 'name').order_by('name')
    
    return JsonResponse({'cities': list(cities)})


@login_required
@require_http_methods(["GET"])
def get_cities_for_country(request, country_id):
    """Get cities for a specific country (AJAX)"""
    
    cities = City.objects.filter(
        country_id=country_id,
        approval_status=ApprovalStatus.APPROVED
    ).values('id', 'name', 'region__name').order_by('name')
    
    return JsonResponse({'cities': list(cities)})
