import logging
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import NotificationDelivery


logger = logging.getLogger(__name__)


def publish_delivery_after_commit(delivery_id):
    def publish():
        if getattr(settings, 'NOTIFICATION_OUTBOX_SYNC', False):
            try:
                process_delivery(delivery_id)
            except Exception:
                logger.exception('notification_delivery_sync_failed', extra={'delivery_id': delivery_id})
            return
        try:
            from reports.tasks import process_notification_delivery_task
            process_notification_delivery_task.delay(delivery_id)
        except Exception:
            logger.exception('notification_delivery_publish_failed', extra={'delivery_id': delivery_id})

    transaction.on_commit(publish)


def process_delivery(delivery_id):
    delivery = _claim_delivery(delivery_id)
    if delivery is None:
        return False

    try:
        if delivery.channel == NotificationDelivery.Channel.WEBSOCKET:
            _send_websocket(delivery)
        elif delivery.channel == NotificationDelivery.Channel.EMAIL:
            _send_email(delivery)
        else:
            raise ValueError(f'Unsupported notification channel: {delivery.channel}')
    except Exception as exc:
        _mark_failed(delivery.id, exc)
        raise

    NotificationDelivery.objects.filter(pk=delivery.id).update(
        status=NotificationDelivery.Status.SENT,
        sent_at=timezone.now(),
        next_retry_at=None,
        last_error='',
        updated_at=timezone.now(),
    )
    return True


def dispatch_pending_deliveries(limit=100):
    now = timezone.now()
    stale_before = now - timedelta(minutes=10)
    NotificationDelivery.objects.filter(
        status=NotificationDelivery.Status.PROCESSING,
        updated_at__lt=stale_before,
    ).update(status=NotificationDelivery.Status.FAILED, next_retry_at=now)

    ids = list(
        NotificationDelivery.objects.filter(
            Q(status=NotificationDelivery.Status.PENDING)
            | Q(status=NotificationDelivery.Status.FAILED, next_retry_at__lte=now),
            attempts__lt=settings.NOTIFICATION_OUTBOX_MAX_ATTEMPTS,
        ).order_by('created_at').values_list('id', flat=True)[:limit]
    )
    for delivery_id in ids:
        try:
            from reports.tasks import process_notification_delivery_task
            process_notification_delivery_task.delay(delivery_id)
        except Exception:
            logger.exception('notification_delivery_publish_failed', extra={'delivery_id': delivery_id})
    return len(ids)


def _claim_delivery(delivery_id):
    now = timezone.now()
    with transaction.atomic():
        delivery = (
            NotificationDelivery.objects.select_for_update()
            .select_related('notification', 'notification__user')
            .filter(pk=delivery_id)
            .first()
        )
        if delivery is None or delivery.status in {
            NotificationDelivery.Status.SENT,
            NotificationDelivery.Status.DEAD,
        }:
            return None
        if delivery.status == NotificationDelivery.Status.PROCESSING:
            return None
        if delivery.next_retry_at and delivery.next_retry_at > now:
            return None
        if delivery.attempts >= settings.NOTIFICATION_OUTBOX_MAX_ATTEMPTS:
            delivery.status = NotificationDelivery.Status.DEAD
            delivery.save(update_fields=['status', 'updated_at'])
            return None
        delivery.status = NotificationDelivery.Status.PROCESSING
        delivery.attempts += 1
        delivery.save(update_fields=['status', 'attempts', 'updated_at'])
        return delivery


def _send_websocket(delivery):
    notification = delivery.notification
    async_to_sync(get_channel_layer().group_send)(
        f'user_{notification.user_id}',
        {
            'type': 'notification_message',
            **delivery.payload,
        },
    )
    notification.is_pushed = True
    notification.save(update_fields=['is_pushed'])


def _send_email(delivery):
    payload = delivery.payload
    send_mail(
        subject=payload['subject'],
        message=payload['message'],
        from_email=payload.get('from_email'),
        recipient_list=payload['recipient_list'],
        html_message=payload.get('html_message'),
        fail_silently=False,
    )


def _mark_failed(delivery_id, exc):
    delivery = NotificationDelivery.objects.get(pk=delivery_id)
    max_attempts = settings.NOTIFICATION_OUTBOX_MAX_ATTEMPTS
    dead = delivery.attempts >= max_attempts
    delay_seconds = min(3600, 2 ** min(delivery.attempts, 10) * 15)
    delivery.status = NotificationDelivery.Status.DEAD if dead else NotificationDelivery.Status.FAILED
    delivery.next_retry_at = None if dead else timezone.now() + timedelta(seconds=delay_seconds)
    delivery.last_error = str(exc)[:2000]
    delivery.save(update_fields=['status', 'next_retry_at', 'last_error', 'updated_at'])
