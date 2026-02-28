from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from reports.models import Notification

@login_required
def notification_list(request):
    """
    通知中心页面视图。
    """
    notifications = request.user.notifications.all()
    
    # 如果请求，按类型过滤
    n_type = request.GET.get('type')
    if n_type:
        notifications = notifications.filter(notification_type=n_type)
        
    return render(request, 'reports/notification_list.html', {
        'notifications': notifications[:50], # 限制为最近 50 条
        'unread_count': notifications.filter(is_read=False).count()
    })

@login_required
@require_POST
def mark_notification_read(request, pk):
    """
    标记单个通知为已读的 API。
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
    标记所有用户通知为已读的 API。
    """
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return JsonResponse({'status': 'success'})

@login_required
def get_unread_count(request):
    """
    获取当前未读计数的 API（用于轮询回退）。
    """
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({'count': count})
