# locations/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import BooleanField, Count, ExpressionWrapper, Prefetch, Q
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import Country, Region, City, POI, PlaceType, LocationStatus, CapitalType
from apps.media_app.models import Media
from apps.approval_system.models import ApprovalStatus
from apps.core.utils.breadcrumbs import BreadcrumbPatterns

from apps.core.ratelimit import limit

from . import city_search as city_search_module
from .forms import CityForm, NewCityForm, POIForm, RegionForm
from .seo import place_meta


def visible(queryset, user):
    """What ``user`` may see of a location queryset (site roadmap R22: the place pages are public):
    staff everything; members approved items and their own submissions; visitors approved only."""
    if user.is_authenticated and (user.is_staff or getattr(user, "can_access_staff", False)):
        return queryset
    approved = Q(approval_status=ApprovalStatus.APPROVED)
    return queryset.filter(approved | Q(submitted_by=user) if user.is_authenticated else approved)


def _status_filter(request, queryset):
    """The lists' Status filter, for staff only (everyone else sees ``visible`` items)."""
    user = request.user
    staff = user.is_authenticated and (user.is_staff or getattr(user, "can_access_staff", False))
    status = request.GET.get('status', 'all') if staff else 'all'
    if status != 'all':
        queryset = queryset.filter(approval_status=status)
    return visible(queryset, user), status, staff


def pictures_first(queryset, *order):
    """Order ``queryset`` with the ones that have a picture first, then by ``order``."""
    has_picture = ExpressionWrapper(Q(featured_media__isnull=False), output_field=BooleanField())
    return queryset.annotate(_has_picture=has_picture).order_by("-_has_picture", *order)



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

def country_list(request):
    """List all countries with filtering"""
    
    search_query = request.GET.get('q', '')
    continent_filter = request.GET.get('continent', '')
    
    countries, status_filter, show_status = _status_filter(request, Country.objects.select_related('featured_media'))
    
    if search_query:
        countries = countries.filter(
            Q(name__icontains=search_query) |
            Q(iso_code__icontains=search_query) |
            Q(iso3_code__icontains=search_query)
        )
    
    if continent_filter:
        countries = countries.filter(continent=continent_filter)
    
    countries = pictures_first(countries, 'name')
    
    # Pagination
    paginator = Paginator(countries, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter, 'show_status_filter': show_status,
        'search_query': search_query,
        'continent_filter': continent_filter,
        'continents': [choice[0] for choice in Country._meta.get_field('continent').choices],
        'breadcrumb_list': BreadcrumbPatterns.countries_list(),
    }
    
    return render(request, 'locations/country_list.html', context)


def country_detail(request, slug):
    """View country details with regions and cities"""
    
    country = get_object_or_404(
        visible(Country.objects.all(), request.user).select_related('featured_media')
        .prefetch_related('regions', 'cities')
        .annotate(
            _city_count=Count('cities', filter=Q(cities__approval_status=ApprovalStatus.APPROVED)),
            _poi_count=Count('cities__pois', filter=Q(cities__pois__approval_status=ApprovalStatus.APPROVED))
        ),
        slug=slug
    )
    
    # Get regions with city count
    regions = pictures_first(visible(country.regions.all(), request.user).annotate(
        total_cities=Count('cities', filter=Q(cities__approval_status=ApprovalStatus.APPROVED))), 'name')
    
    # Get major cities
    cities = pictures_first(country.cities.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('region', 'featured_media'), '-population')[:10]
    
    # Get featured POIs
    featured_pois = POI.objects.filter(
        city__country=country,
        approval_status=ApprovalStatus.APPROVED
    ).select_related('city', 'featured_media', 'poi_type')
    featured_pois = pictures_first(featured_pois, '-visitor_count', 'name')[:8]
    
    context = {
        'country': country, 'can_edit': can_edit(request.user, country),
        'regions': regions,
        'cities': cities,
        'featured_pois': featured_pois,
        'breadcrumb_list': BreadcrumbPatterns.country_detail(country),
        'seo': place_meta('country', country),
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
        
        # Its flag (country-flags plan C1): the picture unless one was chosen above.
        from . import flags
        flags.attach(country)

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
    if not can_edit(request.user, country):
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
        # "Use the flag" (country-flags plan C1): the flag back as the picture, whatever else was chosen.
        if request.POST.get('use_flag') and country.flag_media_id:
            country.featured_media_id = country.flag_media_id
        
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

def region_list(request):
    """List all regions with filtering"""
    
    country_id = request.GET.get('country')
    search_query = request.GET.get('q', '')
    
    regions, status_filter, show_status = _status_filter(request, Region.objects.select_related('country', 'featured_media'))
    
    if country_id:
        regions = regions.filter(country_id=country_id)
    
    if search_query:
        regions = regions.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(country__name__icontains=search_query)
        )
    
    regions = pictures_first(regions, 'country__name', 'name')
    
    # Pagination
    paginator = Paginator(regions, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by('name')
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter, 'show_status_filter': show_status,
        'search_query': search_query,
        'countries': countries,
        'selected_country': country_id,
        'breadcrumb_list': BreadcrumbPatterns.regions_list
    }
    
    return render(request, 'locations/region_list.html', context)


def region_detail(request, slug):
    """View region details"""
    
    region = get_object_or_404(
        visible(Region.objects.all(), request.user).select_related('country', 'featured_media')
        .prefetch_related('cities')
        .annotate(_city_count=Count('cities', filter=Q(cities__approval_status=ApprovalStatus.APPROVED))),
        slug=slug
    )
    
    # Get cities in this region
    cities = pictures_first(region.cities.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('featured_media'), '-population')
    
    context = {
        'region': region, 'can_edit': can_edit(request.user, region),
        'cities': cities,
        'breadcrumb_list': BreadcrumbPatterns.region_detail(region),
        'seo': place_meta('region', region),
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

def city_list(request):
    """List all cities with filtering"""
    
    country_id = request.GET.get('country')
    region_id = request.GET.get('region')
    search_query = request.GET.get('q', '')
    capital_only = request.GET.get('capital') == 'true'
    
    cities, status_filter, show_status = _status_filter(request, City.objects.select_related('country', 'region', 'featured_media'))
    
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
    
    cities = pictures_first(cities, 'country__name', 'name')
    
    # Pagination
    paginator = Paginator(cities, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by('name')
    
    context = {
        'page_obj': page_obj,
        'status_filter': status_filter, 'show_status_filter': show_status,
        'search_query': search_query,
        'countries': countries,
        'regions': Region.objects.filter(country__approval_status=ApprovalStatus.APPROVED).order_by('name'),
        'selected_country': country_id,
        'selected_region': region_id,
        'capital_only': capital_only,
        'breadcrumb_list': BreadcrumbPatterns.cities_list
    }
    
    return render(request, 'locations/city_list.html', context)


def city_detail(request, slug):
    """View city details"""
    
    city = get_object_or_404(
        visible(City.objects.all(), request.user).select_related('country', 'region', 'featured_media')
        .prefetch_related('pois')
        .annotate(_poi_count=Count('pois', filter=Q(pois__approval_status=ApprovalStatus.APPROVED))),
        slug=slug
    )
    
    # Get POIs in this city
    pois = city.pois.filter(
        approval_status=ApprovalStatus.APPROVED
    ).select_related('featured_media', 'poi_type')
    pois = pictures_first(pois, '-visitor_count', 'name')
    
    context = {
        'city': city, 'can_edit': can_edit(request.user, city),
        'pois': pois,
        'breadcrumb_list': BreadcrumbPatterns.city_detail(city),
        'seo': place_meta('city', city),
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
        
        # Check for duplicates: cities are unique per region (Kansas City MO / KS)
        if City.objects.filter(country=country, region=region, name__iexact=name).exists():
            messages.error(request, 'This city already exists in the selected region and country.')
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


@limit("city_search", 120, 60, methods=("GET",))
def city_search(request):
    """JSON for the type-to-search city box (day-first plan, P1): up to 10 cities matching ``q``,
    best first (``city_search.search``), optionally in one ``country`` (ISO code or id)."""
    found = city_search_module.search(request.GET.get("q", "")[:100], request.user,
                                      country=request.GET.get("country", "").strip()[:10] or None)
    return JsonResponse({"results": [city_search_module.as_json(city) for city in found]})


@login_required
def country_options(request):
    """Approved countries, for the box's "Add a new city" form."""
    countries = Country.objects.filter(approval_status=ApprovalStatus.APPROVED).order_by("name")
    return JsonResponse({"countries": [{"id": c.pk, "name": c.name} for c in countries]})


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "fetch" or "json" in request.headers.get("Accept", "")


def _new_city_coordinates(name, region, country):
    from apps.core.geocoding import geocode
    found = geocode(", ".join(part for part in (name, region.name if region else "", country.name) if part))
    if found:
        return found
    if country.latitude is not None and country.longitude is not None:
        return country.latitude, country.longitude
    return 0, 0


@login_required
@limit("city_new", 20, 3600)
def city_new(request):
    """Add a city that isn't in the catalogue yet, from the city search box (or this page without
    JavaScript): pending, the submitter's to use at once, in the approval queue for staff. A city
    the member can already see under that name is returned instead of a second one."""
    from django.utils.http import url_has_allowed_host_and_scheme
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
        next_url = ""
    form = NewCityForm(request.POST or None, initial={"name": request.GET.get("name", "")})
    if request.method == "POST":
        if not form.is_valid():
            if _wants_json(request):
                return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
        else:
            name, country, region = (form.cleaned_data[k] for k in ("name", "country", "region"))
            city = (city_search_module.visible_cities(request.user)
                    .filter(name__iexact=name, country=country, region=region).first())
            if city is None:
                if City.objects.filter(name__iexact=name, country=country, region=region).exists():
                    form.add_error("name", "That city has already been suggested and is waiting for review.")
                    if _wants_json(request):
                        return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
                else:
                    latitude, longitude = _new_city_coordinates(name, region, country)
                    city = City.objects.create(name=name, country=country, region=region, latitude=latitude,
                                               longitude=longitude, submitted_by=request.user,
                                               approval_status=ApprovalStatus.PENDING)
                    city.submit_for_review(request.user)
            if city is not None:
                city = City.objects.select_related("region", "country").get(pk=city.pk)
                if _wants_json(request):
                    return JsonResponse({"city": city_search_module.as_json(city)})
                messages.success(request, f"Added {city}. You can use it now; staff will review it.")
                return redirect(next_url or reverse("locations:city_detail", args=[city.slug]))
    return render(request, "locations/city_new.html", {"form": form, "next": next_url})


# ============================================================================
# POI VIEWS
# ============================================================================

def _place_filters(request, pois):
    """Apply the Places filters shared by the list and the map (search, country, type,
    city) to ``pois``; returns the queryset and the values as given."""
    filters = {name: request.GET.get(name, '') for name in ('q', 'country', 'type', 'city')}
    if filters['city'].isdigit():
        pois = pois.filter(city_id=filters['city'])
    if filters['country'].isdigit():
        pois = pois.filter(city__country_id=filters['country'])
    if filters['type']:
        pois = pois.filter(poi_type_id=filters['type'])
    if filters['q']:
        q = filters['q']
        pois = pois.filter(Q(name__icontains=q) | Q(city__name__icontains=q) | Q(description__icontains=q))
    return pois, filters


def _place_filter_choices():
    return {
        'poi_types': PlaceType.choices(),
        # Only countries that have places, so every choice finds something.
        'countries': Country.objects.filter(cities__pois__isnull=False).distinct().order_by('name'),
    }


def poi_map(request):
    """All published places on a map, with the same filters as the Places list."""
    _, filters = _place_filters(request, POI.objects.none())
    return render(request, 'locations/poi_map.html', {
        **_place_filter_choices(),
        'search_query': filters['q'], 'selected_type': filters['type'], 'selected_country': filters['country'],
        'map_data_url': reverse('locations:poi_map_data') + (f"?{request.GET.urlencode()}" if request.GET else ''),
        'breadcrumb_list': BreadcrumbPatterns.pois_list,
    })


def poi_map_data(request):
    """Published places as GeoJSON (the map's data; provider-neutral)."""
    pois = POI.objects.filter(approval_status=ApprovalStatus.APPROVED).select_related(
        'city__country', 'poi_type', 'featured_media')
    pois, _ = _place_filters(request, pois)
    features = []
    for poi in pois.order_by('name'):
        media = poi.featured_media
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [float(poi.longitude), float(poi.latitude)]},
            'properties': {
                'name': poi.name,
                'subtitle': f"{poi.poi_type.name} · {poi.city.name}, {poi.city.country.name}",
                'url': reverse('locations:poi_detail', args=[poi.slug]),
                'image': media.file.url if media and media.media_type == 'image' else '',
            },
        })
    return JsonResponse({'type': 'FeatureCollection', 'features': features})


def poi_list(request):
    """List all POIs with filtering"""
    
    pois, status_filter, show_status = _status_filter(
        request, POI.objects.select_related('city', 'city__country', 'featured_media', 'poi_type'))
    pois, filters = _place_filters(request, pois)
    search_query, poi_type, country_id = filters['q'], filters['type'], filters['country']

    pois = pictures_first(pois, 'city__country__name', 'city__name', 'name')
    
    # Pagination
    paginator = Paginator(pois, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        **_place_filter_choices(),
        'page_obj': page_obj,
        'status_filter': status_filter, 'show_status_filter': show_status,
        'search_query': search_query,
        'selected_type': poi_type,
        'selected_country': country_id,
        'breadcrumb_list': BreadcrumbPatterns.pois_list
    }
    
    return render(request, 'locations/poi_list.html', context)


def poi_detail(request, slug):
    """View POI details"""
    
    poi = get_object_or_404(
        visible(POI.objects.all(), request.user).select_related('city', 'city__country', 'city__region', 'featured_media', 'poi_type'),
        slug=slug
    )
        
    context = {
        'poi': poi, 'can_edit': can_edit(request.user, poi),
        'breadcrumb_list': BreadcrumbPatterns.poi_detail(poi),
        'seo': place_meta('place', poi),
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
        
        if poi_type and not PlaceType.objects.filter(code=poi_type).exists():
            poi_type = None
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
            poi_type_id=poi_type,
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
    
    poi_types = PlaceType.choices()
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


# ============================================================================
# EDIT PAGES (region, city, place)
# ============================================================================

def can_edit(user, obj):
    """Staff, or whoever submitted it (as on the country edit page)."""
    return user.is_authenticated and (
        user.is_staff or getattr(user, "can_access_staff", False) or obj.submitted_by_id == user.pk)


def _edit(request, obj, form_class, kind, detail_url, breadcrumbs):
    if not can_edit(request.user, obj):
        messages.error(request, f"You do not have permission to edit this {kind}.")
        return redirect(detail_url, slug=obj.slug)
    form = form_class(request.POST or None, request.FILES or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        form.save_picture(request.user)
        messages.success(request, f"{kind.capitalize()} “{obj.name}” updated.")
        return redirect(detail_url, slug=obj.slug)
    return render(request, "locations/location_edit.html", {
        "form": form, "obj": obj, "kind": kind, "cancel_url": detail_url, "breadcrumb_list": breadcrumbs,
    })


@login_required
def region_edit(request, slug):
    region = get_object_or_404(Region, slug=slug)
    return _edit(request, region, RegionForm, "region", "locations:region_detail", BreadcrumbPatterns.region_edit(region))


@login_required
def city_edit(request, slug):
    city = get_object_or_404(City.objects.select_related("country", "region"), slug=slug)
    return _edit(request, city, CityForm, "city", "locations:city_detail", BreadcrumbPatterns.city_edit(city))


@login_required
def poi_edit(request, slug):
    poi = get_object_or_404(POI.objects.select_related("city"), slug=slug)
    return _edit(request, poi, POIForm, "place", "locations:poi_detail", BreadcrumbPatterns.poi_edit(poi))
