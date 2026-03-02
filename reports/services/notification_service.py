import json
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from reports.models import Notification
from core.services.notification_template import NotificationContent, NotificationTemplateService

import logging
from reports.tasks import send_email_async_task

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

def send_notification(user, title, message, notification_type, data=None, priority='normal', content: NotificationContent = None):
    """
    发送通知：
    1. 写入数据库 Notification
    2. WebSocket 实时推送 (如果用户设置开启 inapp)
    3. 异步发送邮件 (如果提供了 content 且用户设置开启 email_instantly)
    """
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

    # 1. 创建数据库记录 (始终创建，作为历史记录)
    notification = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        priority=priority,
        data=data or {},
        expires_at=timezone.now() + timezone.timedelta(days=30) # Default 30 days
    )

    # 2. 推送到 WebSocket（仅限高/普通优先级或特定类型，且用户允许）
    if allow_inapp and priority in ['high', 'normal']:
        try:
            channel_layer = get_channel_layer()
            group_name = f"user_{user.id}"
            
            async_to_sync(channel_layer.group_send)(
                group_name,
                {
                    'type': 'notification_message',
                    'notification_type': notification_type,
                    'title': title,
                    'message': message,
                    'priority': priority,
                    'created_at': notification.created_at.isoformat(),
                    'data': data or {}
                }
            )
            notification.is_pushed = True
            notification.save(update_fields=['is_pushed'])
        except Exception as e:
            logger.error(f"Failed to push notification to {user.username}: {e}")

    # 3. 发送电子邮件（异步，且用户允许）
    if allow_email and content and user.email:
        try:
            html_message = NotificationTemplateService.render_email(content)
            subject = content.email_subject
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
            
            # Use Celery task instead of Thread
            send_email_async_task.delay(
                subject=subject,
                message=content.body,
                from_email=from_email,
                recipient_list=[user.email],
                html_message=html_message
            )
            
        except Exception as e:
            logger.error(f"Failed to trigger email to {user.email}: {e}")
    
    return notification
