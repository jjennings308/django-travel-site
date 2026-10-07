# activities/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.utils import timezone
from .models import Activity, ActivityCategory, UserActivityBookmark
from .forms import ActivityCreateForm, ActivityEditForm, ActivityQuickCreateForm
from approval_system.models import ApprovalStatus


def activity_list(request):
    """Public list of approved activities"""
    activities = Activity.get_public_activities()
    
    # Filtering
    category_slug = request.GET.get('category')
    if category_slug:
        activities = activities.filter(category__slug=category_slug)
    
    skill_level = request.GET.get('skill')
    if skill_level:
        activities = activities.filter(skill_level=skill_level)
    
    cost_level = request.GET.get('cost')
    if cost_level:
        activities = activities.filter(cost_level=cost_level)
    
    best_for = request.GET.get('for')
    if best_for:
        activities = activities.filter(best_for=best_for)
    
    # Search
    search = request.GET.get('q')
    if search:
        activities = activities.filter(
            Q(name__icontains=search) |
            Q(description__icontains=search) |
            Q(short_description__icontains=search)
        )
    
    # Sorting
    sort = request.GET.get('sort', '-popularity_score')
    valid_sorts = ['-popularity_score', 'name', '-created_at', '-bucket_list_count']
    if sort in valid_sorts:
        activities = activities.order_by(sort)
    
    # Pagination
    paginator = Paginator(activities, 24)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get categories for filter
    categories = ActivityCategory.objects.filter(is_active=True)
    
    context = {
        'page_obj': page_obj,
        'categories': categories,
        'current_category': category_slug,
        'current_sort': sort,
    }
    
    return render(request, 'activities/activity_list.html', context)


def activity_detail(request, slug):
    """View a single activity"""
    activity = get_object_or_404(Activity, slug=slug)
    
    # Check visibility
    if not activity.is_visible_to(request.user):
        return HttpResponseForbidden("You don't have permission to view this activity.")
    
    # Check if user has bookmarked this
    is_bookmarked = False
    if request.user.is_authenticated:
        is_bookmarked = UserActivityBookmark.objects.filter(
            user=request.user,
            activity=activity
        ).exists()
    
    context = {
        'activity': activity,
        'is_bookmarked': is_bookmarked,
        'can_edit': activity.can_edit(request.user),
        'can_delete': activity.can_delete(request.user),
    }
    
    return render(request, 'activities/activity_detail.html', context)


@login_required
def my_activities(request):
    """User's own activities (private and public)"""
    activities = Activity.get_user_activities(request.user)
    
    # Filter by status
    status = request.GET.get('status')
    if status:
        activities = activities.filter(approval_status=status)
    
    visibility = request.GET.get('visibility')
    if visibility:
        activities = activities.filter(visibility=visibility)
    
    # Pagination
    paginator = Paginator(activities.order_by('-created_at'), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
        'current_status': status,
        'current_visibility': visibility,
    }
    
    return render(request, 'activities/my_activities.html', context)


@login_required
def activity_add(request):
    """Create a new activity"""
    if request.method == 'POST':
        form = ActivityCreateForm(request.POST, user=request.user)
        if form.is_valid():
            activity = form.save()
            
            if activity.visibility == 'public':
                if request.user.is_staff:
                    messages.success(request, 'Activity created and approved!')
                else:
                    messages.success(request, 'Activity created and submitted for approval!')
            else:
                messages.success(request, 'Private activity created!')
            
            return redirect('activities:activity_detail', slug=activity.slug)
    else:
        form = ActivityCreateForm(user=request.user)
    
    context = {
        'form': form,
        'title': 'Create Activity',
    }
    
    return render(request, 'activities/activity_form.html', context)


@login_required
def activity_quick_add(request):
    """Quick add with minimal fields"""
    if request.method == 'POST':
        form = ActivityQuickCreateForm(request.POST, user=request.user)
        if form.is_valid():
            activity = form.save()
            messages.success(request, 'Activity created! You can add more details later.')
            return redirect('activities:activity_edit', slug=activity.slug)
    else:
        form = ActivityQuickCreateForm(user=request.user)
    
    context = {
        'form': form,
        'title': 'Quick Add Activity',
    }
    
    return render(request, 'activities/activity_quick_form.html', context)


@login_required
def activity_edit(request, slug):
    """Edit an existing activity"""
    activity = get_object_or_404(Activity, slug=slug)
    
    # Check permission
    if not activity.can_edit(request.user):
        messages.error(request, "You don't have permission to edit this activity.")
        return redirect('activities:activity_detail', slug=slug)
    
    if request.method == 'POST':
        form = ActivityEditForm(request.POST, instance=activity)
        if form.is_valid():
            form.save()
            messages.success(request, 'Activity updated!')
            return redirect('activities:activity_detail', slug=activity.slug)
    else:
        form = ActivityEditForm(instance=activity)
    
    context = {
        'form': form,
        'activity': activity,
        'title': f'Edit: {activity.name}',
    }
    
    return render(request, 'activities/activity_form.html', context)


@login_required
def activity_delete(request, slug):
    """Delete an activity"""
    activity = get_object_or_404(Activity, slug=slug)
    
    # Check permission
    if not activity.can_delete(request.user):
        messages.error(request, "You don't have permission to delete this activity.")
        return redirect('activities:activity_detail', slug=slug)
    
    if request.method == 'POST':
        activity_name = activity.name
        activity.delete()
        messages.success(request, f'Activity "{activity_name}" deleted.')
        return redirect('activities:my_activities')
    
    context = {
        'activity': activity,
    }
    
    return render(request, 'activities/activity_confirm_delete.html', context)


@login_required
def activity_submit_for_public(request, slug):
    """Submit a private/draft activity for public approval"""
    activity = get_object_or_404(Activity, slug=slug, created_by=request.user)
    
    if request.method == 'POST':
        activity.submit_for_public(request.user)
        messages.success(request, 'Activity submitted for approval! We\'ll review it soon.')
        return redirect('activities:activity_detail', slug=slug)
    
    context = {
        'activity': activity,
    }
    
    return render(request, 'activities/activity_submit_confirm.html', context)


@login_required
def activity_make_private(request, slug):
    """Change activity back to private"""
    activity = get_object_or_404(Activity, slug=slug, created_by=request.user)
    
    # Can only make private if not already approved
    if activity.approval_status == ApprovalStatus.APPROVED:
        messages.error(request, 'Cannot make an approved activity private. Please contact staff.')
        return redirect('activities:activity_detail', slug=slug)
    
    if request.method == 'POST':
        activity.make_private()
        messages.success(request, 'Activity changed to private.')
        return redirect('activities:activity_detail', slug=slug)
    
    context = {
        'activity': activity,
    }
    
    return render(request, 'activities/activity_make_private_confirm.html', context)


@login_required
def activity_bookmark(request, slug):
    """Bookmark an activity"""
    activity = get_object_or_404(Activity, slug=slug)
    
    # Check visibility
    if not activity.is_visible_to(request.user):
        return HttpResponseForbidden()
    
    bookmark, created = UserActivityBookmark.objects.get_or_create(
        user=request.user,
        activity=activity
    )
    
    if created:
        messages.success(request, f'Bookmarked "{activity.name}"!')
    else:
        messages.info(request, 'Already bookmarked.')
    
    # Redirect back to referrer or activity detail
    return redirect(request.META.get('HTTP_REFERER', 'activities:activity_detail'), slug=slug)


@login_required
def activity_unbookmark(request, slug):
    """Remove bookmark from activity"""
    activity = get_object_or_404(Activity, slug=slug)
    
    UserActivityBookmark.objects.filter(
        user=request.user,
        activity=activity
    ).delete()
    
    messages.success(request, f'Removed bookmark from "{activity.name}".')
    
    return redirect(request.META.get('HTTP_REFERER', 'activities:activity_detail'), slug=slug)


@login_required
def my_bookmarks(request):
    """View user's bookmarked activities"""
    bookmarks = UserActivityBookmark.objects.filter(
        user=request.user
    ).select_related('activity', 'activity__category')
    
    # Pagination
    paginator = Paginator(bookmarks, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,
    }
    
    return render(request, 'activities/my_bookmarks.html', context)
