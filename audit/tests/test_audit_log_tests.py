
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from projects.models import Project, ProjectAttachment
from tasks.models import Task
from audit.models import AuditLog
from audit.middleware import AuditMiddleware
import json

class AuditLogTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='password')
        self.project = Project.objects.create(
            name="Test Project",
            code="TP-001",
            owner=self.user,
            description="Initial"
        )
        
        # Mock Request for Middleware
        self.factory = RequestFactory()
        
    def _mock_request_user(self, user):
        # We need to simulate the middleware setting thread locals
        # But signals run synchronously. We can manually set the thread local?
        # Or better, use the middleware in a context manager way if possible.
        # But signals.py imports get_current_user from middleware.
        # We can just set the thread local directly for testing signals.
        from audit.middleware import _thread_locals
        _thread_locals.user = user
        _thread_locals.ip = '127.0.0.1'

    def tearDown(self):
        from audit.middleware import _thread_locals
        if hasattr(_thread_locals, 'user'): del _thread_locals.user
        if hasattr(_thread_locals, 'ip'): del _thread_locals.ip

    def test_project_update_logs(self):
        self._mock_request_user(self.user)
        
        # Update Name
        self.project.name = "New Name"
        self.project.save()
        
        log = AuditLog.objects.filter(target_type='Project', target_id=str(self.project.id)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.action, 'update')
        self.assertIn('name', log.details['diff'])
        self.assertEqual(log.details['diff']['name'][0], "Test Project")
        self.assertEqual(log.details['diff']['name'][1], "New Name")

    def test_none_vs_empty_string_ignored(self):
        self._mock_request_user(self.user)
        
        # Project.description is blank=True, not null. DB has "Initial".
        # Update to ""
        self.project.description = ""
        self.project.save()
        
        log = AuditLog.objects.first()
        self.assertIn('description', log.details['diff'])
        self.assertEqual(log.details['diff']['description'][0], "Initial")
        self.assertEqual(log.details['diff']['description'][1], "")
        
        # Now update "" to "" (should be ignored)
        AuditLog.objects.all().delete()
        self.project.save() # No change
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_generic_foreign_key_logging(self):
        self._mock_request_user(self.user)
        user2 = User.objects.create_user(username='user2')
        
        self.project.owner = user2
        self.project.save()
        
        log = AuditLog.objects.first()
        self.assertIn('owner', log.details['diff'])
        # Depending on get_full_name empty
        self.assertEqual(log.details['diff']['owner'][0], 'tester')
        self.assertEqual(log.details['diff']['owner'][1], 'user2')

    def test_task_creation_and_update(self):
        self._mock_request_user(self.user)
        
        t = Task.objects.create(
            title="Task 1",
            project=self.project,
            user=self.user,
            status='todo'
        )
        
        # Check create log
        log = AuditLog.objects.filter(target_type='Task', target_id=str(t.id), action='create').first()
        self.assertIsNotNone(log)
        
        # Update Status
        t.status = 'in_progress'
        t.save()
        
        log = AuditLog.objects.filter(target_type='Task', target_id=str(t.id), action='update').first()
        diff = log.details['diff']
        self.assertIn('status', diff)
        # Check Labels
        self.assertIn('To Do', diff['status'][0]) # Should match "待处理 / To Do"
        self.assertIn('In Progress', diff['status'][1])

    def test_m2m_changes(self):
        self._mock_request_user(self.user)
        user2 = User.objects.create_user(username='member1')
        
        self.project.members.add(user2)
        
        log = AuditLog.objects.filter(target_type='Project', action='update').order_by('-created_at').first()
        self.assertIsNotNone(log)
        self.assertIn('members', log.details['diff'])
        self.assertEqual(log.details['diff']['members']['action'], 'Added')
        self.assertIn('member1', log.details['diff']['members']['values'])

    def test_attachment_upload(self):
        self._mock_request_user(self.user)
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        f = SimpleUploadedFile("test.txt", b"content")
        att = ProjectAttachment.objects.create(
            project=self.project,
            uploaded_by=self.user,
            file=f,
            original_filename="test.txt"
        )
        
        log = AuditLog.objects.filter(target_type='Project', action='upload').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details['filename'], 'test.txt')

    def test_completed_at_logging(self):
        self._mock_request_user(self.user)
        t = Task.objects.create(
            title="Task 2",
            project=self.project,
            user=self.user,
            status='todo'
        )
        
        from django.utils import timezone
        now = timezone.now()
        t.completed_at = now
        t.save()
        
        log = AuditLog.objects.filter(target_type='Task', target_id=str(t.id), action='update').order_by('-created_at').first()
        self.assertIn('completed_at', log.details['diff'])

    def test_idempotency(self):
        """Ensure repeated updates in short window do not create duplicate logs."""
        self._mock_request_user(self.user)
        
        # Clear existing logs from setUp
        AuditLog.objects.all().delete()
        
        self.project.name = "Duplicate Check"
        self.project.save()
        
        # 1. First save should create a log (Update)
        # Debugging duplicate issue
        if AuditLog.objects.count() != 1:
            logs = list(AuditLog.objects.values('action', 'target_type', 'details', 'user_id', 'created_at'))
            self.fail(f"Expected 1 log, got {AuditLog.objects.count()}. Logs: {logs}")
            
        self.assertEqual(AuditLog.objects.count(), 1)
        
        # Reset
        AuditLog.objects.all().delete()

        # Simulation:
        # Create a log manually, then try to save() to trigger signal that would produce same log.
        
        # Reset project name
        self.project.name = "Original"
        self.project.save()
        AuditLog.objects.all().delete() # Start clean
        self.assertEqual(AuditLog.objects.count(), 0, "Delete failed")
        
        # 1. Simulate Request A completing
        self.project.name = "Changed"
        self.project.save()
        self.assertEqual(AuditLog.objects.count(), 1)
        
        # 2. Simulate Request B (which started earlier but finishes now)
        # It thinks old was "Original" and new is "Changed".
        
        # So to test the debounce, we can just manually invoke the signal handler `log_model_changes`.
        from audit.signals import log_model_changes
        
        # Call it again with same instance
        log_model_changes(sender=Project, instance=self.project, created=False)
        
        # Should still be 1 because of debounce
        self.assertEqual(AuditLog.objects.count(), 1)
        

    def test_audit_log_service(self):
        from audit.services import AuditLogService
        self._mock_request_user(self.user)
        
        # Create some history
        self.project.name = "Service Test"
        self.project.save()
        
        # Get history (QuerySet)
        qs = AuditLogService.get_history(self.project)
        self.assertTrue(qs.exists())
        
        # Format logs
        history = []
        for log in qs:
            entry = AuditLogService.format_log_entry(log)
            if entry:
                history.append(entry)

        self.assertGreaterEqual(len(history), 1)
        # Find the update log
        update_entry = next((h for h in history if h['action'] == 'update'), None)
        self.assertIsNotNone(update_entry)
        
        # Check items structure
        # AuditLogService now converts keys to verbose names
        # Project.name verbose_name is "项目名称"
        self.assertIn('项目名称', update_entry['changes'])
        self.assertEqual(update_entry['changes']['项目名称'][0], "Test Project") # From setUp
        self.assertEqual(update_entry['changes']['项目名称'][1], "Service Test")
        
        # Filter by field
        # The filter still uses internal field name 'name'
        qs_name = AuditLogService.get_history(self.project, {'field_name': 'name'})
        self.assertTrue(qs_name.exists())
        
        # Verify formatting with filter
        history_name = []
        for log in qs_name:
            entry = AuditLogService.format_log_entry(log, field_filter='name')
            if entry: history_name.append(entry)
        self.assertGreaterEqual(len(history_name), 1)
        # Verify verbose name key is present in filtered result too
        self.assertIn('项目名称', history_name[0]['changes'])
        
        # Filter by non-existent field
        qs_desc = AuditLogService.get_history(self.project, {'field_name': 'description'})
        self.assertFalse(qs_desc.exists())
