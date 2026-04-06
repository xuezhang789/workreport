from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Profile
from reports.models import Notification


User = get_user_model()


class NotificationCenterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='notify_user',
            email='notify@example.com',
            password='password123',
        )
        Profile.objects.create(user=self.user, position='dev')

        self.other_user = User.objects.create_user(
            username='other_user',
            email='other@example.com',
            password='password123',
        )
        Profile.objects.create(user=self.other_user, position='qa')

        self.client = Client()
        self.client.login(username='notify_user', password='password123')

        self.notifications = []
        for index in range(23):
            notification = Notification.objects.create(
                user=self.user,
                title=f'Notification {index}',
                message=f'Message {index}',
                notification_type='task_updated' if index % 2 else 'project_update',
                priority='high' if index % 5 == 0 else 'normal',
                is_read=index % 3 == 0,
                data={'task_id': index + 1},
            )
            self.notifications.append(notification)

        self.other_notification = Notification.objects.create(
            user=self.other_user,
            title='Other Notification',
            message='Should not be touched',
            notification_type='project_update',
            is_read=True,
        )

    def test_dropdown_notification_list_api_is_paginated(self):
        response = self.client.get(
            reverse('reports:notification_list_api'),
            {'page': 2, 'per_page': 5},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertEqual(payload['page'], 2)
        self.assertEqual(payload['per_page'], 5)
        self.assertEqual(payload['total_pages'], 5)
        self.assertEqual(payload['total_count'], 23)
        self.assertTrue(payload['has_previous'])
        self.assertTrue(payload['has_next'])
        self.assertEqual(len(payload['notifications']), 5)
        self.assertIn('priority', payload['notifications'][0])

    def test_delete_notification_api_only_deletes_current_users_notification(self):
        target = self.notifications[1]

        response = self.client.post(
            reverse('reports:delete_notification_api', args=[target.id])
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertTrue(payload['success'])
        self.assertEqual(payload['deleted_count'], 1)
        self.assertFalse(Notification.objects.filter(pk=target.id).exists())
        self.assertTrue(Notification.objects.filter(pk=self.other_notification.id).exists())

    def test_delete_read_notifications_only_clears_read_records_for_current_user(self):
        user_read_count = Notification.objects.filter(user=self.user, is_read=True).count()
        unread_count = Notification.objects.filter(user=self.user, is_read=False).count()

        response = self.client.post(reverse('reports:delete_read_notifications_api'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        self.assertTrue(payload['success'])
        self.assertEqual(payload['deleted_count'], user_read_count)
        self.assertEqual(payload['unread_count'], unread_count)
        self.assertEqual(Notification.objects.filter(user=self.user, is_read=True).count(), 0)
        self.assertTrue(Notification.objects.filter(pk=self.other_notification.id).exists())

    def test_notification_page_renders_delete_controls_and_pagination(self):
        response = self.client.get(reverse('reports:notification_list'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="clear-read-page"')
        self.assertContains(response, 'data-notification-action="delete"')
        self.assertContains(response, 'class="page-current"')
        self.assertContains(response, '末页 / Last')
