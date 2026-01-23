# trips/views.py
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q, Count, Sum, Avg
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from datetime import datetime, timedelta

from .models import Trip, TripBooking, TripActivity, TripDay
from .forms import (
    PastTripForm, NewTripForm, BookingForm,
    QuickBookFlightForm, QuickBookHotelForm,
    TripReviewForm, UpdateTripStatusForm
)
from .services.booking_api import (
    get_flight_api, get_hotel_api, get_activity_api, get_payment_processor
)


@login_required
def dashboard(request):
    """
    Main trips dashboard showing all trips organized by status
    """
    user_trips = Trip.objects.filter(user=request.user)
    
    # Get trips by status
    upcoming_trips = user_trips.filter(
        status__in=['planning', 'booked'],
        start_date__gte=timezone.now().date()
    ).order_by('start_date')[:5]
    
    current_trips = user_trips.filter(
        status='in_progress',
        start_date__lte=timezone.now().date(),
        end_date__gte=timezone.now().date()
    )
    
    past_trips = user_trips.filter(
        Q(status='completed') | Q(end_date__lt=timezone.now().date())
    ).order_by('-end_date')[:5]
    
    # Stats
    total_trips = user_trips.count()
    total_countries = user_trips.aggregate(
        count=Count('countries', distinct=True)
    )['count'] or 0
    
    total_spent = user_trips.filter(
        actual_cost__isnull=False
    ).aggregate(
        total=Sum('actual_cost')
    )['total'] or 0
    
    avg_rating = user_trips.filter(
        overall_rating__isnull=False
    ).aggregate(
        avg=Avg('overall_rating')
    )['avg'] or 0
    
    context = {
        "app_name": "Trips",
        "page_title": "Trips Dashboard",
        "upcoming_trips": upcoming_trips,
        "current_trips": current_trips,
        "past_trips": past_trips,
        "stats": {
            "total_trips": total_trips,
            "total_countries": total_countries,
            "total_spent": round(total_spent, 2),
            "avg_rating": round(avg_rating, 1) if avg_rating else None,
        }
    }
    
    return render(request, "trips/dashboard.html", context)


@login_required
def trip_list(request):
    """List all trips with filtering"""
    trips = Trip.objects.filter(user=request.user)
    
    # Filtering
    status = request.GET.get('status')
    if status:
        trips = trips.filter(status=status)
    
    trip_type = request.GET.get('trip_type')
    if trip_type:
        trips = trips.filter(trip_type=trip_type)
    
    year = request.GET.get('year')
    if year:
        trips = trips.filter(start_date__year=year)
    
    context = {
        'trips': trips.order_by('-start_date'),
        'status_choices': Trip.STATUS_CHOICES,
        'trip_type_choices': Trip.TRIP_TYPES,
    }
    
    return render(request, 'trips/trip_list.html', context)


@login_required
def trip_detail(request, trip_id):
    """View trip details"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    # Get related data
    bookings = trip.bookings.all().order_by('start_date')
    days = trip.days.all().order_by('date')
    activities = TripActivity.objects.filter(trip_day__trip=trip).order_by('trip_day__date', 'start_time')
    
    context = {
        'trip': trip,
        'bookings': bookings,
        'days': days,
        'activities': activities,
        'can_review': trip.status == 'completed' and not trip.overall_rating,
    }
    
    return render(request, 'trips/trip_detail.html', context)


# ============================================
# ADDING PAST TRIPS
# ============================================

@login_required
def add_past_trip(request):
    """Add a trip that already occurred"""
    if request.method == 'POST':
        # UPDATED: Pass user to form
        form = PastTripForm(request.POST, user=request.user)
        if form.is_valid():
            trip = form.save(commit=False)
            trip.user = request.user
            trip.save()
            form.save_m2m()  # Save many-to-many relationships
            
            messages.success(
                request,
                f'Past trip "{trip.title}" has been added successfully!'
            )
            return redirect('trips:trip_detail', trip_id=trip.id)
    else:
        # UPDATED: Pass user to form
        form = PastTripForm(user=request.user)
    
    context = {
        'form': form,
        'page_title': 'Add Past Trip',
        'submit_text': 'Add Trip'
    }
    
    return render(request, 'trips/trip_form.html', context)


# ============================================
# PLANNING NEW TRIPS
# ============================================

@login_required
def plan_new_trip(request):
    """Plan a new upcoming trip"""
    if request.method == 'POST':
        # UPDATED: Pass user to form
        form = NewTripForm(request.POST, user=request.user)
        if form.is_valid():
            trip = form.save(commit=False)
            trip.user = request.user
            trip.save()
            form.save_m2m()
            
            messages.success(
                request,
                f'Trip "{trip.title}" is now being planned! Start adding activities and bookings.'
            )
            return redirect('trips:trip_detail', trip_id=trip.id)
    else:
        # UPDATED: Pass user to form
        form = NewTripForm(user=request.user)
    
    context = {
        'form': form,
        'page_title': 'Plan New Trip',
        'submit_text': 'Create Trip'
    }
    
    return render(request, 'trips/trip_form.html', context)


@login_required
def edit_trip(request, trip_id):
    """Edit an existing trip"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    # Use appropriate form based on trip status
    if trip.status == 'completed':
        FormClass = PastTripForm
    else:
        FormClass = NewTripForm
    
    if request.method == 'POST':
        # UPDATED: Pass user to form
        form = FormClass(request.POST, instance=trip, user=request.user)
        if form.is_valid():
            trip = form.save()
            messages.success(request, f'Trip "{trip.title}" updated successfully!')
            return redirect('trips:trip_detail', trip_id=trip.id)
    else:
        # UPDATED: Pass user to form
        form = FormClass(instance=trip, user=request.user)
    
    context = {
        'form': form,
        'trip': trip,
        'page_title': f'Edit {trip.title}',
        'submit_text': 'Update Trip'
    }
    
    return render(request, 'trips/trip_form.html', context)


# ============================================
# BOOKING TRIPS
# ============================================

@login_required
def book_trip(request, trip_id):
    """Main booking interface for a trip"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    # Get existing bookings
    bookings = trip.bookings.all().order_by('start_date')
    
    context = {
        'trip': trip,
        'bookings': bookings,
        'flight_form': QuickBookFlightForm(),
        'hotel_form': QuickBookHotelForm(),
    }
    
    return render(request, 'trips/book_trip.html', context)


@login_required
def search_flights(request, trip_id):
    """Search for flights using the booking API"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    if request.method == 'POST':
        form = QuickBookFlightForm(request.POST)
        if form.is_valid():
            flight_api = get_flight_api()
            
            # Search for flights
            results = flight_api.search_flights(
                origin=form.cleaned_data['origin'],
                destination=form.cleaned_data['destination'],
                departure_date=form.cleaned_data['departure_date'],
                return_date=form.cleaned_data.get('return_date'),
                passengers=form.cleaned_data['passengers'],
                cabin_class=form.cleaned_data['cabin_class']
            )
            
            context = {
                'trip': trip,
                'form': form,
                'results': results,
                'search_params': form.cleaned_data,
            }
            
            return render(request, 'trips/flight_results.html', context)
    else:
        # Pre-fill form with trip details
        initial = {
            'destination': trip.primary_destination.name if trip.primary_destination else '',
            'departure_date': trip.start_date,
            'return_date': trip.end_date,
            'passengers': trip.traveler_count,
        }
        form = QuickBookFlightForm(initial=initial)
    
    context = {
        'trip': trip,
        'form': form,
    }
    
    return render(request, 'trips/search_flights.html', context)


@login_required
def search_hotels(request, trip_id):
    """Search for hotels using the booking API"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    if request.method == 'POST':
        form = QuickBookHotelForm(request.POST)
        if form.is_valid():
            hotel_api = get_hotel_api()
            
            # Search for hotels
            results = hotel_api.search_hotels(
                destination=form.cleaned_data['destination'],
                check_in=form.cleaned_data['check_in'],
                check_out=form.cleaned_data['check_out'],
                rooms=form.cleaned_data['rooms'],
                guests=form.cleaned_data['guests'],
                max_price=form.cleaned_data.get('max_price')
            )
            
            context = {
                'trip': trip,
                'form': form,
                'results': results,
                'search_params': form.cleaned_data,
            }
            
            return render(request, 'trips/hotel_results.html', context)
    else:
        # Pre-fill form with trip details
        initial = {
            'destination': trip.primary_destination.name if trip.primary_destination else '',
            'check_in': trip.start_date,
            'check_out': trip.end_date,
            'guests': trip.traveler_count,
        }
        form = QuickBookHotelForm(initial=initial)
    
    context = {
        'trip': trip,
        'form': form,
    }
    
    return render(request, 'trips/search_hotels.html', context)


@login_required
def add_booking(request, trip_id):
    """Manually add a booking to a trip"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    if request.method == 'POST':
        # UPDATED: Pass user to form
        form = BookingForm(request.POST, user=request.user)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.trip = trip
            booking.status = 'confirmed'
            booking.save()
            
            messages.success(request, 'Booking added successfully!')
            return redirect('trips:book_trip', trip_id=trip.id)
    else:
        # UPDATED: Pass user to form
        form = BookingForm(user=request.user)
    
    context = {
        'trip': trip,
        'form': form,
        'page_title': 'Add Booking',
    }
    
    return render(request, 'trips/booking_form.html', context)


@login_required
@require_http_methods(["POST"])
def confirm_booking_api(request, trip_id):
    """
    Confirm a booking from API search results.
    This would integrate with the actual booking API.
    """
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    # Get booking details from POST
    booking_type = request.POST.get('booking_type')
    item_id = request.POST.get('item_id')
    
    # Mock booking confirmation
    # In production, this would call the appropriate API
    if booking_type == 'flight':
        flight_api = get_flight_api()
        confirmation = flight_api.book_flight(
            item_id,
            {"name": request.user.get_full_name()}
        )
    elif booking_type == 'hotel':
        hotel_api = get_hotel_api()
        confirmation = hotel_api.book_hotel(
            item_id,
            {"name": request.user.get_full_name()}
        )
    else:
        return JsonResponse({'error': 'Invalid booking type'}, status=400)
    
    if confirmation.get('success'):
        # Create booking record
        booking = TripBooking.objects.create(
            trip=trip,
            booking_type=booking_type,
            title=request.POST.get('title', 'Booking'),
            confirmation_number=confirmation['confirmation_number'],
            booking_url=confirmation.get('booking_url', ''),
            cost=confirmation['total_amount'],
            currency=confirmation['currency'],
            status='confirmed',
            payment_status='unpaid',
            start_date=trip.start_date,  # Should come from form
        )
        
        # Update trip status to booked if it was in planning
        if trip.status == 'planning':
            trip.status = 'booked'
            trip.save()
        
        messages.success(request, f'Booking confirmed! Confirmation #: {confirmation["confirmation_number"]}')
        return redirect('trips:trip_detail', trip_id=trip.id)
    else:
        messages.error(request, 'Booking failed. Please try again.')
        return redirect('trips:book_trip', trip_id=trip.id)


# ============================================
# REVIEWING TRIPS
# ============================================

@login_required
def review_trip(request, trip_id):
    """Add a review/rating to a completed trip"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    # Only allow reviews for completed trips
    if trip.status != 'completed' and trip.end_date >= timezone.now().date():
        messages.warning(request, 'You can only review completed trips.')
        return redirect('trips:trip_detail', trip_id=trip.id)
    
    if request.method == 'POST':
        form = TripReviewForm(request.POST)
        if form.is_valid():
            form.save(trip)
            messages.success(request, 'Thank you for reviewing your trip!')
            return redirect('trips:trip_detail', trip_id=trip.id)
    else:
        # Pre-fill with existing review data if any
        initial = {}
        if trip.overall_rating:
            initial['overall_rating'] = trip.overall_rating
        if trip.trip_summary:
            initial['trip_summary'] = trip.trip_summary
        if trip.highlights:
            initial['highlights'] = trip.highlights
        
        form = TripReviewForm(initial=initial)
    
    context = {
        'trip': trip,
        'form': form,
        'page_title': f'Review: {trip.title}',
    }
    
    return render(request, 'trips/review_trip.html', context)


# ============================================
# TRIP STATUS MANAGEMENT
# ============================================

@login_required
def update_trip_status(request, trip_id):
    """Update the status of a trip"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    
    if request.method == 'POST':
        form = UpdateTripStatusForm(request.POST)
        if form.is_valid():
            old_status = trip.status
            trip.status = form.cleaned_data['status']
            
            # Add notes if provided
            notes = form.cleaned_data.get('notes')
            if notes:
                trip.notes = f"{trip.notes}\n\nStatus changed from {old_status} to {trip.status}:\n{notes}".strip()
            
            trip.save()
            
            messages.success(
                request,
                f'Trip status updated to {trip.get_status_display()}'
            )
            return redirect('trips:trip_detail', trip_id=trip.id)
    else:
        form = UpdateTripStatusForm(initial={'status': trip.status})
    
    context = {
        'trip': trip,
        'form': form,
    }
    
    return render(request, 'trips/update_status.html', context)


@login_required
@require_http_methods(["POST"])
def delete_trip(request, trip_id):
    """Delete a trip"""
    trip = get_object_or_404(Trip, id=trip_id, user=request.user)
    trip_title = trip.title
    trip.delete()
    
    messages.success(request, f'Trip "{trip_title}" has been deleted.')
    return redirect('trips:dashboard')


# ============================================
# ANALYTICS & STATS
# ============================================

@login_required
def trip_stats(request):
    """View trip statistics and analytics"""
    user_trips = Trip.objects.filter(user=request.user)
    
    # Calculate various statistics
    stats = {
        'total_trips': user_trips.count(),
        'completed_trips': user_trips.filter(status='completed').count(),
        'countries_visited': user_trips.aggregate(
            count=Count('countries', distinct=True)
        )['count'] or 0,
        'total_days_traveled': user_trips.aggregate(
            total=Sum('day_count')
        )['total'] or 0,
        'total_spent': user_trips.filter(
            actual_cost__isnull=False
        ).aggregate(
            total=Sum('actual_cost')
        )['total'] or 0,
        'avg_trip_cost': user_trips.filter(
            actual_cost__isnull=False
        ).aggregate(
            avg=Avg('actual_cost')
        )['avg'] or 0,
        'avg_rating': user_trips.filter(
            overall_rating__isnull=False
        ).aggregate(
            avg=Avg('overall_rating')
        )['avg'] or 0,
    }
    
    # Trips by type
    trips_by_type = user_trips.values('trip_type').annotate(
        count=Count('id')
    ).order_by('-count')
    
    # Trips by year
    trips_by_year = user_trips.values(
        'start_date__year'
    ).annotate(
        count=Count('id')
    ).order_by('-start_date__year')
    
    context = {
        'stats': stats,
        'trips_by_type': trips_by_type,
        'trips_by_year': trips_by_year,
    }
    
    return render(request, 'trips/stats.html', context)
