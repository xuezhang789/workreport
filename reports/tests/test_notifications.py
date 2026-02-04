from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from reports.models import Notification, Task, Project
from reports.services.notification_service import send_notification
from reports.signals import notify_task_assignment
from core.models import Profile

class NotificationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        Profile.objects.create(user=self.user, position='dev')
        
        self.manager = User.objects.create_user('manager', 'mgr@example.com', 'password')
        Profile.objects.create(user=self.manager, position='pm')
        
        self.project = Project.objects.create(name="Test Project", owner=self.manager)
        self.project.members.add(self.user)

    def test_send_notification_priority(self):
        """Test notification creation with priority."""
        n_high = send_notification(
            user=self.user,
            title="High Priority",
            message="Testing high priority",
            notification_type="system",
            priority="high"
        )
        self.assertEqual(n_high.priority, "high")
        
        n_normal = send_notification(
            user=self.user,
            title="Normal Priority",
            message="Testing normal priority",
            notification_type="system"
        )
        self.assertEqual(n_normal.priority, "normal")

    def test_task_assignment_signal(self):
        """Test that task creation triggers notification."""
        task = Task.objects.create(
            title="New Task",
            project=self.project,
            user=self.user,
            status='todo',
            priority='high'
        )
        
        # Check notification
        notifications = Notification.objects.filter(user=self.user, notification_type='task_assigned')
        self.assertTrue(notifications.exists())
        self.assertEqual(notifications.first().priority, 'high')
