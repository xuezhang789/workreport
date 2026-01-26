import json
from django.utils import timezone
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from reports.models import Notification

def send_notification(user, title, message, notification_type, data=None):
    """
    Creates a notification record and pushes it via WebSocket.
    """
    if not user:
        return None

    # 1. Create DB Record
    notification = Notification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        data=data or {},
        expires_at=timezone.now() + timezone.timedelta(days=30) # Default 30 days
    )

    # 2. Push to WebSocket
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
                'created_at': notification.created_at.isoformat(),
                'data': data or {}
            }
        )
        notification.is_pushed = True
        notification.save(update_fields=['is_pushed'])
    except Exception as e:
        print(f"Failed to push notification to {user.username}: {e}")
        # We don't fail the transaction, just log it. The DB record is still there.
    
    return notification
