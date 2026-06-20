import os
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import ExportJob
from core.services.maintenance import cleanup_expired_export_jobs, recover_stale_export_jobs


class RuntimeMaintenanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('maintenance-user', password='password')
        fd, self.export_path = tempfile.mkstemp(prefix='expired-export-', suffix='.csv')
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.export_path):
            os.remove(self.export_path)

    def test_cleanup_expired_export_jobs_removes_file_and_marks_failed(self):
        job = ExportJob.objects.create(
            user=self.user,
            export_type='my_tasks',
            status='done',
            progress=100,
            file_path=self.export_path,
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        result = cleanup_expired_export_jobs()

        job.refresh_from_db()
        self.assertEqual(result, {'files': 1, 'jobs': 1})
        self.assertEqual(job.status, 'failed')
        self.assertFalse(os.path.exists(self.export_path))

    @override_settings(EXPORT_JOB_STALE_MINUTES=10)
    def test_recover_stale_export_jobs_marks_stuck_running_jobs_failed(self):
        job = ExportJob.objects.create(
            user=self.user,
            export_type='my_tasks',
            status='running',
            progress=50,
            expires_at=timezone.now() + timedelta(days=1),
        )
        ExportJob.objects.filter(id=job.id).update(updated_at=timezone.now() - timedelta(minutes=30))

        count = recover_stale_export_jobs()

        job.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(job.status, 'failed')
        self.assertIn('Worker heartbeat lost', job.message)
