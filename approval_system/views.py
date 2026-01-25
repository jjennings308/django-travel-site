# approval_system/views.py
"""
Views for the unified approval dashboard.
All pending content across the site in one place.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Q, Avg
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta

from .models import (
    ApprovalLog, ApprovalRule, ApprovalQueue, 
    ApprovalSettings, ApprovalStatus, ApprovalPriority
)


@staff_member_required
def approval_dashboard(request):
    """
    Unified approval dashboard showing all pending content.
    """
    settings = ApprovalSettings.get_settings()
    
    # Get all queues
    queues = ApprovalQueue.objects.filter(is_active=True).prefetch_related(
        'content_types', 'reviewers'
    )
    
    # Calculate stats for each queue
    queue_stats = []
    total_pending = 0
    
    for queue in queues:
        count = queue.get_pending_count()
        queue_stats.append({
            'queue': queue,
            'count': count,
            'color': queue.color,
            'icon': queue.icon,
        })
        total_pending += count
    
    # Get recent activity
    recent_logs = ApprovalLog.objects.select_related(
        'performed_by', 'content_type'
    )[:20]
    
    # Get items needing urgent attention (SLA breached)
    sla_hours = settings.review_sla_hours
    sla_cutoff = timezone.now() - timedelta(hours=sla_hours)
    
    # Count overdue items across all approvable models
    overdue_count = 0
    # This would need to dynamically query all models that use Approvable
    # For now, placeholder
    
    # Get stats by priority
    priority_stats = {
        'urgent': 0,
        'high': 0,
        'normal': 0,
        'low': 0,
    }
    # Would populate from actual models
    
    context = {
        'queue_stats': queue_stats,
        'total_pending': total_pending,
        'recent_logs': recent_logs,
        'overdue_count': overdue_count,
        'sla_hours': sla_hours,
        'priority_stats': priority_stats,
        'settings': settings,
    }
    
    return render(request, 'approval_system/dashboard.html', context)


@staff_member_required
def queue_detail(request, queue_slug):
    """
    View items in a specific approval queue.
    """
    queue = get_object_or_404(ApprovalQueue, slug=queue_slug, is_active=True)
    settings = ApprovalSettings.get_settings()
    
    # Get all items for this queue
    items = []
    
    for content_type in queue.content_types.all():
        model = content_type.model_class()
        if model and hasattr(model, 'approval_status'):
            queryset = model.objects.filter(approval_status=queue.status_filter)
            
            if queue.priority_filter:
                queryset = queryset.filter(approval_priority=queue.priority_filter)
            
            queryset = queryset.select_related('submitted_by', 'reviewed_by')
            queryset = queryset.order_by('-submitted_at')[:settings.items_per_page]
            
            for obj in queryset:
                items.append({
                    'object': obj,
                    'content_type': content_type,
                    'model_name': content_type.model,
                    'app_label': content_type.app_label,
                })
    
    # Sort by submitted_at
    items.sort(key=lambda x: x['object'].submitted_at or timezone.now(), reverse=True)
    
    context = {
        'queue': queue,
        'items': items,
        'settings': settings,
    }
    
    return render(request, 'approval_system/queue_detail.html', context)


@staff_member_required
def review_item(request, content_type_id, object_id):
    """
    Review a specific item (works for any approvable model).
    """
    content_type = get_object_or_404(ContentType, id=content_type_id)
    model = content_type.model_class()
    
    if not model or not hasattr(model, 'approval_status'):
        messages.error(request, 'Invalid content type')
        return redirect('approval_system:dashboard')
    
    item = get_object_or_404(model, id=object_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        priority = request.POST.get('priority')
        
        # Update priority if changed
        if priority and priority != item.approval_priority:
            old_priority = item.approval_priority
            item.approval_priority = priority
            item.save()
            
            ApprovalLog.objects.create(
                content_object=item,
                action='priority_changed',
                performed_by=request.user,
                notes=f'Priority changed from {old_priority} to {priority}',
                metadata={'old_priority': old_priority, 'new_priority': priority}
            )
        
        # Perform approval action
        if action == 'approve':
            item.approve(request.user, notes)
            messages.success(request, f'{content_type.model} approved successfully!')
        elif action == 'reject':
            item.reject(request.user, notes)
            messages.warning(request, f'{content_type.model} rejected.')
        elif action == 'request_changes':
            item.request_changes(request.user, notes)
            messages.info(request, f'Changes requested for {content_type.model}.')
        
        # Redirect back to dashboard or stay on page
        next_url = request.POST.get('next', 'approval_system:dashboard')
        return redirect(next_url)
    
    # Get approval history
    history = item.get_approval_history()
    
    context = {
        'item': item,
        'content_type': content_type,
        'model_name': content_type.model,
        'history': history,
        'priority_choices': ApprovalPriority.choices,
    }
    
    return render(request, 'approval_system/review_item.html', context)


@staff_member_required
@require_POST
def bulk_action(request):
    """
    Handle bulk approval actions.
    """
    action = request.POST.get('action')
    items = request.POST.getlist('items[]')  # Format: "content_type_id:object_id"
    notes = request.POST.get('notes', '')
    
    if not items:
        return JsonResponse({'success': False, 'error': 'No items selected'})
    
    success_count = 0
    error_count = 0
    
    for item_id in items:
        try:
            content_type_id, object_id = item_id.split(':')
            content_type = ContentType.objects.get(id=content_type_id)
            model = content_type.model_class()
            obj = model.objects.get(id=object_id)
            
            if action == 'approve':
                obj.approve(request.user, notes or f'Bulk approved by {request.user.username}')
            elif action == 'reject':
                obj.reject(request.user, notes or f'Bulk rejected by {request.user.username}')
            elif action == 'request_changes':
                obj.request_changes(request.user, notes or 'Changes requested')
            
            success_count += 1
        except Exception as e:
            error_count += 1
    
    return JsonResponse({
        'success': True,
        'success_count': success_count,
        'error_count': error_count,
        'action': action
    })


@login_required
def my_submissions(request):
    """
    Show user's own submissions across all content types.
    """
    settings = ApprovalSettings.get_settings()
    
    # Get all content types that have approvable models
    # This would need to be more dynamic in production
    submissions = []
    
    # Example for one model - you'd loop through all approvable models
    from django.apps import apps
    
    for model in apps.get_models():
        if hasattr(model, 'approval_status') and hasattr(model, 'submitted_by'):
            queryset = model.objects.filter(
                submitted_by=request.user
            ).select_related('reviewed_by')
            
            content_type = ContentType.objects.get_for_model(model)
            
            for obj in queryset:
                submissions.append({
                    'object': obj,
                    'content_type': content_type,
                    'model_name': content_type.model,
                })
    
    # Sort by submission date
    submissions.sort(
        key=lambda x: getattr(x['object'], 'submitted_at', None) or timezone.now(),
        reverse=True
    )
    
    context = {
        'submissions': submissions,
    }
    
    return render(request, 'approval_system/my_submissions.html', context)


@staff_member_required
def approval_stats(request):
    """
    Statistics and analytics for the approval system.
    """
    # Time period filter
    days = int(request.GET.get('days', 30))
    start_date = timezone.now() - timedelta(days=days)
    
    # Get logs for the period
    logs = ApprovalLog.objects.filter(created_at__gte=start_date)
    
    # Stats by action
    action_stats = logs.values('action').annotate(count=Count('id')).order_by('-count')
    
    # Stats by reviewer
    reviewer_stats = logs.filter(
        performed_by__isnull=False
    ).values(
        'performed_by__username'
    ).annotate(
        count=Count('id')
    ).order_by('-count')[:10]
    
    # Average review time
    # Would need to calculate time between submission and review
    
    # Stats by content type
    content_type_stats = logs.values(
        'content_type__model'
    ).annotate(
        count=Count('id')
    ).order_by('-count')
    
    context = {
        'days': days,
        'action_stats': action_stats,
        'reviewer_stats': reviewer_stats,
        'content_type_stats': content_type_stats,
    }
    
    return render(request, 'approval_system/stats.html', context)


# API Views

@staff_member_required
def api_pending_counts(request):
    """
    API endpoint to get pending counts for all queues.
    """
    queues = ApprovalQueue.objects.filter(is_active=True)
    
    counts = {}
    total = 0
    
    for queue in queues:
        count = queue.get_pending_count()
        counts[queue.slug] = {
            'name': queue.name,
            'count': count,
            'color': queue.color,
        }
        total += count
    
    counts['total'] = total
    
    return JsonResponse(counts)


@staff_member_required
def api_review_stats(request):
    """
    API endpoint for quick stats.
    """
    today = timezone.now().date()
    
    stats = {
        'today': {
            'approved': ApprovalLog.objects.filter(
                created_at__date=today,
                action='approved'
            ).count(),
            'rejected': ApprovalLog.objects.filter(
                created_at__date=today,
                action='rejected'
            ).count(),
        },
        'this_week': {
            # Would calculate weekly stats
        },
    }
    
    return JsonResponse(stats)
