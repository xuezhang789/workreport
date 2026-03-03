from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from reports.models import Notification

from django.core.paginator import Paginator

@login_required
def notification_list(request):
    """
    通知中心页面视图。
    """
    # 默认按时间倒序
    notifications = request.user.notifications.all().order_by('-created_at')
    
    # 过滤参数
    filter_param = request.GET.get('filter') # all, unread, task, mention, system
    
    if filter_param == 'unread':
        notifications = notifications.filter(is_read=False)
    elif filter_param == 'task':
        notifications = notifications.filter(notification_type__contains='task')
    elif filter_param == 'mention':
        notifications = notifications.filter(notification_type__contains='mention')
    elif filter_param == 'system':
        # 排除 task 和 mention
        notifications = notifications.exclude(notification_type__contains='task').exclude(notification_type__contains='mention')
    elif filter_param == 'sla':
         notifications = notifications.filter(notification_type__contains='sla')
        
    # 分页
    paginator = Paginator(notifications, 20) # 每页 20 条
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
        
    return render(request, 'reports/notification_list.html', {
        'notifications': page_obj,
        'page_obj': page_obj,
        'unread_count': request.user.notifications.filter(is_read=False).count(),
        'current_filter': filter_param or 'all'
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
