from django.utils import timezone
from django.conf import settings
from django.db import transaction
from core.models import Notification, NotificationDelivery, NotificationType
from core.services.notification_template import NotificationContent, NotificationTemplateService
from core.services.notification_delivery import publish_delivery_after_commit

import logging
logger = logging.getLogger(__name__)

def send_weekly_digest_email(user, stats):
    """
    发送周报邮件给指定用户。
    从 reports/statistics_views.py 迁移而来，支持模板化（未来）。
    """
    try:
        subject = f"周报 / Weekly Digest: {timezone.localdate().isoformat()}"
        
        # 指标摘要
        total = stats.get('overall_total', 0)
        completed = stats.get('overall_completed', 0)
        overdue = stats.get('overall_overdue', 0)
        rate = stats.get('overall_rate', 0)
        
        # 构建纯文本内容
        message = f"""
        你好 / Hello {user.get_full_name() or user.username},
        
        这是您的本周工作简报 / Here is your weekly work digest:
        
        --- 总体概况 / Overview ---
        任务总数 / Total Tasks: {total}
        已完成 / Completed: {completed}
        逾期任务 / Overdue: {overdue}
        完成率 / Completion Rate: {rate:.1f}%
        
        --- 项目详情 / Projects ---
        """
        
        for p in stats.get('project_stats', []):
            message += f"\nProject: {p['name']}\n"
            message += f"  Total: {p['total']}, Done: {p['completed']}, Overdue: {p['overdue']}\n"
            
        message += "\n\n请登录系统查看详情 / Please login to view details."
        
        # 异步发送
        from reports.tasks import send_email_async_task
        send_email_async_task.delay(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=None # 未来可扩展 HTML 模板
        )
        return True
    except Exception as e:
        logger.exception(f"Failed to send weekly digest to {user.email}: {e}")
        return False

def send_notification(
    user,
    title,
    message,
    notification_type,
    data=None,
    priority='normal',
    content: NotificationContent = None,
    idempotency_key=None,
):
    """
    发送通知：
    1. 写入数据库 Notification
    2. WebSocket 实时推送 (如果用户设置开启 inapp)
    3. 异步发送邮件 (如果提供了 content 且用户设置开启 email_instantly)
    """
    try:
        notification_type = NotificationType(notification_type).value
    except ValueError as exc:
        raise ValueError(f'Unsupported notification type: {notification_type}') from exc
    if priority not in dict(Notification.PRIORITY_CHOICES):
        raise ValueError(f'Unsupported notification priority: {priority}')

    # 获取用户偏好
    # 注意：UserPreference 可能不存在，需要安全获取
    allow_inapp = True
    allow_email = True
    
    if hasattr(user, 'preferences'):
        try:
            # preferences 是 OneToOneField
            prefs = user.preferences.data.get('notify', {})
            # 默认为 True
            allow_inapp = prefs.get('inapp', True)
            allow_email = prefs.get('email_instantly', True)
        except Exception:
            pass

    defaults = {
        'user': user,
        'title': title,
        'message': message,
        'notification_type': notification_type,
        'priority': priority,
        'data': data or {},
        'expires_at': timezone.now() + timezone.timedelta(days=30),
    }
    with transaction.atomic():
        if idempotency_key:
            notification, created = Notification.objects.get_or_create(
                user=user,
                idempotency_key=idempotency_key,
                defaults={key: value for key, value in defaults.items() if key != 'user'},
            )
            if not created:
                return notification
        else:
            notification = Notification.objects.create(**defaults)

        deliveries = []
        if allow_inapp and priority in {'high', 'normal'}:
            deliveries.append(NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationDelivery.Channel.WEBSOCKET,
                payload={
                    'notification_type': notification_type,
                    'id': notification.id,
                    'title': title,
                    'message': message,
                    'priority': priority,
                    'created_at': notification.created_at.isoformat(),
                    'data': data or {},
                },
            ))

        if allow_email and content and user.email:
            deliveries.append(NotificationDelivery.objects.create(
                notification=notification,
                channel=NotificationDelivery.Channel.EMAIL,
                payload={
                    'subject': content.email_subject,
                    'message': content.body,
                    'from_email': getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    'recipient_list': [user.email],
                    'html_message': NotificationTemplateService.render_email(content),
                },
            ))

        for delivery in deliveries:
            publish_delivery_after_commit(delivery.id)

    return notification
