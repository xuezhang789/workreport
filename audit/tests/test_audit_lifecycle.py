from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from audit.models import AuditLog, AuditLogArchive
from audit.services import archive_old_audit_logs
from core.constants import TaskStatus
from projects.models import Project
from tasks.models import Task


class AuditLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='audit-lifecycle-user', password='password')
        self.project = Project.objects.create(name='Audit Lifecycle Project', code='ALP', owner=self.user)
        self.task = Task.objects.create(
            title='Archived task',
            project=self.project,
            user=self.user,
            status=TaskStatus.TODO,
        )
        AuditLog.objects.all().delete()

    def test_archive_old_audit_logs_preserves_snapshot_and_deletes_hot_row(self):
        log = AuditLog.objects.create(
            user=self.user,
            operator_name='Audit User',
            action='update',
            target_type='Task',
            target_id=str(self.task.id),
            target_label='Archived task',
            summary='status changed',
            details={'diff': {'status': {'old': 'todo', 'new': 'done'}}},
            project=self.project,
            task=self.task,
            result='success',
        )
        old_created_at = timezone.now() - timedelta(days=400)
        AuditLog.objects.filter(pk=log.pk).update(created_at=old_created_at)

        result = archive_old_audit_logs(days=365, batch_size=1)

        self.assertEqual(result['archived'], 1)
        self.assertEqual(result['deleted'], 1)
        self.assertFalse(AuditLog.objects.filter(pk=log.pk).exists())

        archive = AuditLogArchive.objects.get(original_id=log.pk)
        self.assertEqual(archive.user_id, self.user.id)
        self.assertEqual(archive.project_id, self.project.id)
        self.assertEqual(archive.task_id, self.task.id)
        self.assertEqual(archive.details['diff']['status']['new'], 'done')

    def test_archive_can_keep_hot_rows_for_dry_run_style_operations(self):
        log = AuditLog.objects.create(
            user=self.user,
            action='access',
            target_type='Project',
            target_id=str(self.project.id),
            project=self.project,
        )
        AuditLog.objects.filter(pk=log.pk).update(created_at=timezone.now() - timedelta(days=500))

        result = archive_old_audit_logs(days=365, delete_after_archive=False)

        self.assertEqual(result['archived'], 1)
        self.assertEqual(result['deleted'], 0)
        self.assertTrue(AuditLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(AuditLogArchive.objects.filter(original_id=log.pk).exists())
