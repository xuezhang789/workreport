from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from reports.models import Notification

@login_required
def notification_list_api(request):
    """
    Get recent notifications for the dropdown.
    """
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
    data = [{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'notification_type': n.notification_type,
        'is_read': n.is_read,
        'created_at': n.created_at.isoformat(),
        'data': n.data,
        'time_since': _time_since(n.created_at)
    } for n in notifications]
    
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    
    return JsonResponse({
        'notifications': data,
        'unread_count': unread_count
    })

@login_required
@require_POST
def mark_read_api(request, pk=None):
    """
    Mark a single notification or all as read.
    """
    if pk:
        # Mark single
        n = get_object_or_404(Notification, pk=pk, user=request.user)
        n.is_read = True
        n.save(update_fields=['is_read'])
        
        # Handle redirection logic if needed
        # For API, just return success
        # If 'next' param is present (e.g. clicking notification redirects), we can handle it in frontend
        return JsonResponse({'success': True})
    else:
        # Mark all
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'success': True})

@login_required
def notification_full_list(request):
    """
    Full page view for notifications.
    """
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    # Pagination could be added here
    return render(request, 'reports/notification_list.html', {'notifications': notifications})

def _time_since(dt):
    from django.utils import timezone
    now = timezone.now()
    diff = now - dt
    
    if diff.days > 0:
        return f"{diff.days}天前"
    elif diff.seconds > 3600:
        return f"{diff.seconds // 3600}小时前"
    elif diff.seconds > 60:
        return f"{diff.seconds // 60}分钟前"
    else:
        return "刚刚"
