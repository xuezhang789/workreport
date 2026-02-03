import json
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from reports.models import Notification
from core.services.notification_template import NotificationContent, NotificationTemplateService

def send_notification(user, title, message, notification_type, data=None, priority='normal', content: NotificationContent = None):
    """
    创建通知记录，通过 WebSocket 推送，并可选择发送电子邮件。
    
    Args:
        content (NotificationContent): 如果提供，则渲染富 HTML 电子邮件并存储结构化数据。
    """
    if not user:
        return None

    # 处理统一内容
    if content:
        if data is None:
            data = {}
        data['rich_content'] = NotificationTemplateService.render_to_dict(content)
        
        # 确保回退文本与内容匹配（除非显式覆盖）
        # 我们暂时坚持使用传递的标题/消息作为数据库记录，
        # 但 'data' 中的 rich_content 将由前端/电子邮件使用。

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
            # 我们不会让事务失败，只是记录它。数据库记录仍然存在。

    # 3. 发送电子邮件（统一逻辑）
    # 仅在提供内容时发送（富文本邮件）或显式请求？
    # 需求称“确保...正确显示...”
    # 因此，如果我们有内容对象，我们假设应该以该格式发送电子邮件。
    if content and user.email:
        try:
            html_message = NotificationTemplateService.render_email(content)
            subject = content.email_subject
            
            send_mail(
                subject=subject,
                message=content.body, # Plain text fallback
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=True
            )
        except Exception as e:
            print(f"Failed to send email to {user.email}: {e}")
    
    return notification
