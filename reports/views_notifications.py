from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from reports.models import Notification


DEFAULT_DROPDOWN_PAGE_SIZE = 8
MAX_DROPDOWN_PAGE_SIZE = 20


def _parse_per_page(raw_value, default=DEFAULT_DROPDOWN_PAGE_SIZE):
    try:
        per_page = int(raw_value)
    except (TypeError, ValueError):
        return default
    return max(1, min(per_page, MAX_DROPDOWN_PAGE_SIZE))


def _serialize_notification(notification):
    return {
        'id': notification.id,
        'title': notification.title,
        'message': notification.message,
        'notification_type': notification.notification_type,
        'priority': notification.priority,
        'is_read': notification.is_read,
        'created_at': notification.created_at.isoformat(),
        'data': notification.data,
        'time_since': _time_since(notification.created_at),
    }


@login_required
def notification_list_api(request):
    """
    Get recent notifications for the dropdown.
    """
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    page_number = request.GET.get('page')
    per_page = _parse_per_page(request.GET.get('per_page'))
    page_obj = Paginator(notifications, per_page).get_page(page_number)
    data = [_serialize_notification(notification) for notification in page_obj.object_list]

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    return JsonResponse({
        'notifications': data,
        'unread_count': unread_count,
        'page': page_obj.number,
        'per_page': per_page,
        'total_pages': page_obj.paginator.num_pages,
        'total_count': page_obj.paginator.count,
        'has_next': page_obj.has_next(),
        'has_previous': page_obj.has_previous(),
    })


@login_required
@require_POST
def mark_read_api(request, pk=None):
    """
    Mark a single notification or all as read.
    """
    if pk:
        # Mark single
        # 标记单个
        n = get_object_or_404(Notification, pk=pk, user=request.user)
        if not n.is_read:
            n.is_read = True
            n.save(update_fields=['is_read'])
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
        return JsonResponse({'success': True, 'unread_count': unread_count, 'notification_id': n.id})
    else:
        # Mark all
        # 标记所有
        updated_count = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return JsonResponse({'success': True, 'unread_count': 0, 'updated_count': updated_count})


@login_required
@require_POST
def delete_notification_api(request, pk):
    """
    Delete a single notification owned by the current user.
    """
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    notification.delete()
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({'success': True, 'deleted_count': 1, 'unread_count': unread_count})


@login_required
@require_POST
def delete_read_notifications_api(request):
    """
    Delete all read notifications for the current user.
    """
    deleted_count, _ = Notification.objects.filter(user=request.user, is_read=True).delete()
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({'success': True, 'deleted_count': deleted_count, 'unread_count': unread_count})


@login_required
def notification_full_list(request):
    """
    Full page view for notifications.
    """
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    # Pagination could be added here
    # 这里可以添加分页
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
