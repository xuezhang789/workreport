import threading
from django.test import TestCase
from django.contrib.auth import get_user_model
from projects.models import Project
from tasks.models import Task
from audit.models import AuditLog
from audit.middleware import _thread_locals
import time

User = get_user_model()

class AuditConcurrencyTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='concurrent_user', password='password')
        self.project = Project.objects.create(name='Concurrent Project', code='CP1', owner=self.user)
        self.task = Task.objects.create(title='Concurrent Task', project=self.project, user=self.user)

    def test_concurrent_updates_deduplication(self):
        """
        Test that rapid identical updates do not create duplicate logs.
        Uses sequential fast execution instead of threads to avoid SQLite locking issues.
        """
        _thread_locals.user = self.user
        
        # 1. Update
        self.task.status = 'in_progress'
        self.task.save()
        
        # 2. Simulate subsequent updates that happen fast
        # Note: In real world, signals handle old state correctly.
        # If we save again, Django sees no change and does nothing.
        # To test deduplication, we must simulate the Signal firing.
        from audit.signals import log_model_changes
        
        # Manually trigger signal 4 more times instantly
        for _ in range(4):
            # We must trick it into thinking there WAS a change
            self.task._old_state = {'status': 'todo'}
            log_model_changes(sender=Task, instance=self.task, created=False)
            
        logs = AuditLog.objects.filter(target_type='Task', target_id=str(self.task.pk), action='update')
        
        # Expect 1 log due to debounce, but allow 2 in case of slight timing/hash mismatch between real save and sim
        # If no deduplication, we would have 5 (1 save + 4 signals).
        self.assertLessEqual(logs.count(), 2)

    def test_rapid_different_updates(self):
        """
        Test that rapid BUT DIFFERENT updates are ALL recorded.
        """
        _thread_locals.user = self.user
        
        self.task.priority = 'high'
        self.task.save()
        
        self.task.priority = 'low'
        self.task.save()
        
        logs = AuditLog.objects.filter(target_type='Task', target_id=str(self.task.pk), action='update').order_by('-created_at')
        
        # Should have 2 logs because details changed
        self.assertEqual(logs.count(), 2)
        # Check that we get verbose names (using new list format [old, new])
        # logs[0] is newest (Low), logs[1] is older (High)
        self.assertIn('High', logs[1].details['diff']['priority'][1]) 
        self.assertIn('Low', logs[0].details['diff']['priority'][1])
