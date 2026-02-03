import json
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from reports.models import Notification
from core.services.notification_template import NotificationContent, NotificationTemplateService

import threading
from django.core.mail import send_mail

def _send_email_async(subject, body, from_email, recipient_list, html_message):
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=from_email,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=True
        )
    except Exception as e:
        print(f"Failed to send email async: {e}")

def send_notification(user, title, message, notification_type, data=None, priority='normal', content: NotificationContent = None):
    # ... (DB and WebSocket logic remains same) ...
    # 1. 创建数据库记录
    notification = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        priority=priority,
        data=data or {},
        expires_at=timezone.now() + timezone.timedelta(days=30) # Default 30 days
    )

    # 2. 推送到 WebSocket（仅限高/普通优先级或特定类型）
    if priority in ['high', 'normal']:
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
            print(f"Failed to push notification to {user.username}: {e}")

    # 3. 发送电子邮件（异步）
    if content and user.email:
        try:
            html_message = NotificationTemplateService.render_email(content)
            subject = content.email_subject
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None)
            
            # Offload to thread (In production, use Celery)
            email_thread = threading.Thread(
                target=_send_email_async,
                args=(subject, content.body, from_email, [user.email], html_message),
                daemon=True
            )
            email_thread.start()
            
        except Exception as e:
            print(f"Failed to trigger email to {user.email}: {e}")
    
    return notification
