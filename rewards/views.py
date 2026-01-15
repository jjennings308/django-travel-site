# ============================================
# rewards/views.py
# ============================================
import logging
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Q, Count

from .models import RewardsProgram, UserRewardsMembership, RewardsProgramType
from .forms import (
    UserRewardsMembershipForm,
    QuickAddRewardsForm,
    RewardsProgramSearchForm
)

logger = logging.getLogger(__name__)


@login_required
def rewards_dashboard(request):
    """Main dashboard showing user's rewards memberships"""
    memberships = request.user.rewards_memberships.select_related(
        'program'
    ).order_by('display_order', 'program__company')
    
    # Group by program type for display
    memberships_by_type = {}
    for membership in memberships:
        prog_type = membership.program.get_program_type_display()
        if prog_type not in memberships_by_type:
            memberships_by_type[prog_type] = []
        memberships_by_type[prog_type].append(membership)
    
    # Get expiring memberships
    expiring_soon = [m for m in memberships if m.is_tier_expiring_soon]
    
    # Stats
    stats = {
        'total_programs': memberships.count(),
        'total_points': sum(
            m.points_balance for m in memberships if m.points_balance
        ),
        'expiring_soon': len(expiring_soon),
        'primary_programs': memberships.filter(is_primary=True).count(),
    }
    
    context = {
        'memberships': memberships,
        'memberships_by_type': memberships_by_type,
        'expiring_soon': expiring_soon,
        'stats': stats,
    }
    
    return render(request, 'rewards/dashboard.html', context)


@login_required
def memberships_list(request):
    """List all user's rewards memberships with filtering"""
    memberships = request.user.rewards_memberships.select_related(
        'program'
    )
    
    # Filter by type
    program_type = request.GET.get('type')
    if program_type and program_type in dict(RewardsProgramType.choices):
        memberships = memberships.filter(program__program_type=program_type)
    
    # Filter by status
    status = request.GET.get('status')
    if status == 'primary':
        memberships = memberships.filter(is_primary=True)
    elif status == 'expiring':
        # Get memberships expiring in next 60 days
        from django.utils import timezone
        from datetime import timedelta
        sixty_days = timezone.now().date() + timedelta(days=60)
        memberships = memberships.filter(
            tier_expires__lte=sixty_days,
            tier_expires__gte=timezone.now().date()
        )
    
    memberships = memberships.order_by('display_order', 'program__company')
    
    context = {
        'memberships': memberships,
        'program_types': RewardsProgramType.choices,
        'current_type': program_type,
        'current_status': status,
    }
    
    return render(request, 'rewards/memberships_list.html', context)


@login_required
def add_membership(request):
    """Add a new rewards program membership"""
    if request.method == 'POST':
        form = UserRewardsMembershipForm(request.POST, user=request.user)
        if form.is_valid():
            membership = form.save()
            messages.success(
                request,
                f'Added {membership.program.name} membership successfully!'
            )
            return redirect('rewards:dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserRewardsMembershipForm(user=request.user)
    
    # Get available programs count by type for help text
    programs_by_type = {}
    for prog_type in RewardsProgramType:
        count = RewardsProgram.objects.filter(
            is_active=True,
            program_type=prog_type.value
        ).count()
        if count > 0:
            programs_by_type[prog_type.label] = count
    
    context = {
        'form': form,
        'programs_by_type': programs_by_type,
    }
    
    return render(request, 'rewards/add_membership.html', context)


@login_required
def edit_membership(request, membership_id):
    """Edit an existing rewards membership"""
    membership = get_object_or_404(
        UserRewardsMembership,
        id=membership_id,
        user=request.user
    )
    
    if request.method == 'POST':
        form = UserRewardsMembershipForm(
            request.POST,
            instance=membership,
            user=request.user
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Membership updated successfully!')
            return redirect('rewards:dashboard')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserRewardsMembershipForm(
            instance=membership,
            user=request.user
        )
    
    context = {
        'form': form,
        'membership': membership,
    }
    
    return render(request, 'rewards/edit_membership.html', context)


@login_required
def membership_detail(request, membership_id):
    """View detailed information about a membership"""
    membership = get_object_or_404(
        UserRewardsMembership,
        id=membership_id,
        user=request.user
    )
    
    context = {
        'membership': membership,
    }
    
    return render(request, 'rewards/membership_detail.html', context)


@login_required
@require_POST
def delete_membership(request, membership_id):
    """Delete a rewards membership"""
    membership = get_object_or_404(
        UserRewardsMembership,
        id=membership_id,
        user=request.user
    )
    
    program_name = membership.program.name
    membership.delete()
    
    messages.success(
        request,
        f'Removed {program_name} membership.'
    )
    return redirect('rewards:dashboard')


@login_required
@require_POST
def reorder_memberships(request):
    """Update display order of memberships via AJAX"""
    try:
        data = json.loads(request.body)
        order = data.get('order', [])
        
        for idx, membership_id in enumerate(order):
            UserRewardsMembership.objects.filter(
                id=membership_id,
                user=request.user
            ).update(display_order=idx)
        
        return JsonResponse({'ok': True})
    except Exception as e:
        logger.error(f"Error reordering memberships: {e}")
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)


@login_required
@require_POST
def toggle_primary(request, membership_id):
    """Toggle primary status of a membership via AJAX"""
    try:
        membership = get_object_or_404(
            UserRewardsMembership,
            id=membership_id,
            user=request.user
        )
        
        membership.is_primary = not membership.is_primary
        membership.save()  # Will auto-unset others due to model save()
        
        return JsonResponse({
            'ok': True,
            'is_primary': membership.is_primary
        })
    except Exception as e:
        logger.error(f"Error toggling primary: {e}")
        return JsonResponse({'ok': False, 'error': str(e)}, status=400)


def programs_browse(request):
    """Browse available rewards programs (public page)"""
    programs = RewardsProgram.objects.filter(is_active=True).annotate(
        member_count=Count('memberships')
    )
    
    # Search and filter
    form = RewardsProgramSearchForm(request.GET)
    if form.is_valid():
        search = form.cleaned_data.get('search')
        if search:
            programs = programs.filter(
                Q(name__icontains=search) |
                Q(company__icontains=search) |
                Q(description__icontains=search)
            )
        
        program_type = form.cleaned_data.get('program_type')
        if program_type:
            programs = programs.filter(program_type=program_type)
    
    # Group by type
    programs_by_type = {}
    for prog_type in RewardsProgramType:
        type_programs = programs.filter(program_type=prog_type.value)
        if type_programs.exists():
            programs_by_type[prog_type.label] = type_programs
    
    context = {
        'programs': programs,
        'programs_by_type': programs_by_type,
        'form': form,
    }
    
    return render(request, 'rewards/programs_browse.html', context)


def program_detail(request, program_id):
    """View details about a specific rewards program"""
    program = get_object_or_404(RewardsProgram, id=program_id, is_active=True)
    
    # Check if user has this membership
    user_membership = None
    if request.user.is_authenticated:
        try:
            user_membership = UserRewardsMembership.objects.get(
                user=request.user,
                program=program
            )
        except UserRewardsMembership.DoesNotExist:
            pass
    
    context = {
        'program': program,
        'user_membership': user_membership,
    }
    
    return render(request, 'rewards/program_detail.html', context)
