from django.test import TestCase, Client
from django.contrib.auth.models import User
from tasks.models import Task
from projects.models import Project
from audit.models import AuditLog, TaskHistory
from core.models import Role, UserRole
from core.services.rbac import RBACService
import json

class TaskAuditHistoryTest(TestCase):
    def setUp(self):
        # Clear logs from setup
        AuditLog.objects.all().delete()
        
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.user = User.objects.create_user('user', 'user@example.com', 'password')
        
        # Setup RBAC for user
        self.project = Project.objects.create(name="Test Project", code="TP", owner=self.admin)
        self.role_dev = RBACService.create_role('Developer', 'dev')
        RBACService.assign_role(self.user, self.role_dev, scope=f"project:{self.project.id}")
        
        # Create Task (This triggers AuditLog via signal)
        self.task = Task.objects.create(
            title="Test Task",
            project=self.project,
            user=self.user,
            status='todo',
            priority='medium'
        )
        # Clear creation logs to focus on update
        AuditLog.objects.all().delete()
        
        self.client = Client()
        self.client.force_login(self.user)

    def test_single_history_record_on_status_change(self):
        # Update status via API/View
        response = self.client.post(f'/tasks/{self.task.id}/view/', {
            'action': 'set_status',
            'status_value': 'in_progress'
        })
        self.assertEqual(response.status_code, 302)
        
        # Check AuditLog
        logs = AuditLog.objects.filter(target_id=str(self.task.id), action='update').order_by('-created_at')
        
        print(f"Total Logs: {logs.count()}")
        for log in logs:
            print(f"Log: {log.action} - Details: {log.details}")
            
        # Verify no TaskHistory (old model) records are created
        self.assertEqual(TaskHistory.objects.filter(task=self.task).count(), 0)
        
        # Verify only ONE detailed data update log exists (the one with 'diff')
        data_logs = [l for l in logs if 'diff' in l.details]
        self.assertEqual(len(data_logs), 1, "Should have exactly one signal-based audit log with diff")
        
        # Verify manual log_action also exists (no diff, just context/data)
        manual_logs = [l for l in logs if 'diff' not in l.details]
        self.assertEqual(len(manual_logs), 1, "Should have exactly one manual log without diff")

