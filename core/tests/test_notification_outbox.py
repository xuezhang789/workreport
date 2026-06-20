from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from core.models import Notification, NotificationDelivery
from core.services.notification_delivery import dispatch_pending_deliveries, process_delivery
from reports.services.notification_service import send_notification


@override_settings(NOTIFICATION_OUTBOX_SYNC=False)
class NotificationOutboxTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('outbox-user', 'outbox@example.com', 'password')

    def test_notification_and_delivery_are_created_atomically(self):
        notification = send_notification(
            self.user,
            'Deployment complete',
            'The release is available.',
            'system',
        )

        delivery = notification.deliveries.get()
        self.assertEqual(delivery.channel, NotificationDelivery.Channel.WEBSOCKET)
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)

    def test_publish_after_commit_uses_fire_and_forget_task(self):
        with patch('reports.tasks.process_notification_delivery_task.apply_async') as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                notification = send_notification(
                    self.user,
                    'Deployment complete',
                    'The release is available.',
                    'system',
                )

        delivery = notification.deliveries.get()
        enqueue.assert_called_once_with((delivery.id,), ignore_result=True, retry=False)

    def test_publish_failure_leaves_delivery_pending_for_retry(self):
        with patch(
            'reports.tasks.process_notification_delivery_task.apply_async',
            side_effect=RuntimeError('redis unavailable'),
        ):
            with self.assertLogs('core.services.notification_delivery', level='WARNING') as logs:
                with self.captureOnCommitCallbacks(execute=True):
                    notification = send_notification(
                        self.user,
                        'Deployment complete',
                        'The release is available.',
                        'system',
                    )

        delivery = notification.deliveries.get()
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)
        self.assertIn('redis unavailable', delivery.last_error)
        self.assertIn('notification_delivery_publish_deferred', '\n'.join(logs.output))

    def test_dispatch_pending_publish_failure_keeps_delivery_pending(self):
        notification = send_notification(self.user, 'Title', 'Message', 'system')
        delivery = notification.deliveries.get()

        with patch(
            'reports.tasks.process_notification_delivery_task.apply_async',
            side_effect=RuntimeError('broker unavailable'),
        ):
            with self.assertLogs('core.services.notification_delivery', level='WARNING'):
                self.assertEqual(dispatch_pending_deliveries(limit=10), 1)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.Status.PENDING)
        self.assertIn('broker unavailable', delivery.last_error)

    def test_idempotency_key_prevents_duplicate_notification(self):
        first = send_notification(
            self.user, 'Same event', 'Payload', 'system', idempotency_key='event:42'
        )
        second = send_notification(
            self.user, 'Same event', 'Payload', 'system', idempotency_key='event:42'
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(Notification.objects.filter(idempotency_key='event:42').count(), 1)
        self.assertEqual(NotificationDelivery.objects.filter(notification=first).count(), 1)

    def test_same_idempotency_key_is_allowed_for_different_users(self):
        other_user = User.objects.create_user('other-outbox-user', password='password')

        first = send_notification(
            self.user, 'Event', 'Payload', 'system', idempotency_key='shared-event:42'
        )
        second = send_notification(
            other_user, 'Event', 'Payload', 'system', idempotency_key='shared-event:42'
        )

        self.assertNotEqual(first.id, second.id)

    def test_successful_delivery_is_marked_sent(self):
        notification = send_notification(self.user, 'Title', 'Message', 'system')
        delivery = notification.deliveries.get()

        with patch('core.services.notification_delivery._send_websocket') as sender:
            self.assertTrue(process_delivery(delivery.id))

        sender.assert_called_once()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.Status.SENT)
        self.assertIsNotNone(delivery.sent_at)

    def test_failed_delivery_is_retriable(self):
        notification = send_notification(self.user, 'Title', 'Message', 'system')
        delivery = notification.deliveries.get()

        with patch(
            'core.services.notification_delivery._send_websocket',
            side_effect=RuntimeError('channel unavailable'),
        ):
            with self.assertRaisesMessage(RuntimeError, 'channel unavailable'):
                process_delivery(delivery.id)

        delivery.refresh_from_db()
        self.assertEqual(delivery.status, NotificationDelivery.Status.FAILED)
        self.assertEqual(delivery.attempts, 1)
        self.assertIsNotNone(delivery.next_retry_at)
