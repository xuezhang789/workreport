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
    Creates a notification record, pushes via WebSocket, and optionally sends Email.
    
    Args:
        content (NotificationContent): If provided, renders a rich HTML email and stores structured data.
    """
    if not user:
        return None

    # Handle Unified Content
    if content:
        if data is None:
            data = {}
        data['rich_content'] = NotificationTemplateService.render_to_dict(content)
        
        # Ensure fallback text matches content if not explicitly overridden (or keep caller's trust)
        # We'll stick to using the passed title/message for the DB record for now, 
        # but the rich_content in 'data' will be used by frontend/email.

    # 1. Create DB Record
    notification = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        priority=priority,
        data=data or {},
        expires_at=timezone.now() + timezone.timedelta(days=30) # Default 30 days
    )

    # 2. Push to WebSocket (Only High/Normal priority or specific types)
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
            # We don't fail the transaction, just log it. The DB record is still there.

    # 3. Send Email (Unified Logic)
    # Only send if content is provided (Rich Email) OR explicit request?
    # Requirement says "ensure ... correct display in ... Email".
    # So if we have the content object, we assume we should send the email in that format.
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
