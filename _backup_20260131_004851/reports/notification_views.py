from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from reports.models import Notification

@login_required
def notification_list(request):
    """
    View for notification center page.
    """
    notifications = request.user.notifications.all()
    
    # Filter by type if requested
    n_type = request.GET.get('type')
    if n_type:
        notifications = notifications.filter(notification_type=n_type)
        
    return render(request, 'reports/notification_list.html', {
        'notifications': notifications[:50], # Limit to recent 50
        'unread_count': notifications.filter(is_read=False).count()
    })

@login_required
@require_POST
def mark_notification_read(request, pk):
    """
    API to mark a single notification as read.
    """
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])
    
    return JsonResponse({'status': 'success'})

@login_required
@require_POST
def mark_all_read(request):
    """
    API to mark all user's notifications as read.
    """
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return JsonResponse({'status': 'success'})

@login_required
def get_unread_count(request):
    """
    API to get current unread count (for polling fallback).
    """
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({'count': count})
