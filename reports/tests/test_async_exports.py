import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.constants import TaskStatus
from core.models import ExportJob, Profile
from core.utils import _create_export_job, _enqueue_export_job
from projects.models import Project
from reports.tasks import generate_export_file_task
from tasks.models import Task
from work_logs.models import DailyReport


class AsyncExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('exporter', password='password')
        Profile.objects.create(user=self.user)
        self.project = Project.objects.create(name='Export Project', code='EXPORT', owner=self.user)
        self.task = Task.objects.create(
            title='Export Task',
            project=self.project,
            user=self.user,
            status=TaskStatus.TODO,
        )
        self.client.force_login(self.user)
        self.generated_files = []

    def tearDown(self):
        for path in self.generated_files:
            if path and os.path.exists(path):
                os.remove(path)

    @patch('reports.tasks.generate_export_file_task.delay')
    def test_enqueue_dispatches_celery_task_and_keeps_job_pending(self, delay):
        job = _create_export_job(self.user, 'my_tasks')

        _enqueue_export_job(job, {'q': 'Export'})

        job.refresh_from_db()
        self.assertEqual(job.status, 'pending')
        self.assertEqual(job.progress, 0)
        delay.assert_called_once_with(job.id, 'my_tasks', {'q': 'Export'})

    @patch('tasks.views.user_views._enqueue_export_job')
    def test_large_export_view_only_enqueues_work(self, enqueue):
        with patch('tasks.views.user_views.MAX_EXPORT_ROWS', 0):
            response = self.client.get(reverse('tasks:task_export'), {'queue': '1'})

        self.assertEqual(response.status_code, 202)
        job = ExportJob.objects.get(id=response.json()['job_id'])
        self.assertEqual(job.status, 'pending')
        enqueue.assert_called_once()

    def test_worker_generates_task_export(self):
        job = _create_export_job(self.user, 'my_tasks')

        path = generate_export_file_task.run(job.id, 'my_tasks', {'q': 'Export'})
        self.generated_files.append(path)

        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertEqual(job.progress, 100)
        self.assertTrue(os.path.exists(job.file_path))
        with open(job.file_path, encoding='utf-8') as export_file:
            contents = export_file.read()
        self.assertIn('Export Task', contents)

    def test_worker_generates_admin_task_export(self):
        job = _create_export_job(self.user, 'admin_tasks')

        path = generate_export_file_task.run(job.id, 'admin_tasks', {'project_id': self.project.id})
        self.generated_files.append(path)

        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        with open(job.file_path, encoding='utf-8') as export_file:
            self.assertIn('Export Task', export_file.read())

    def test_worker_generates_permission_filtered_admin_report_export(self):
        admin = User.objects.create_superuser('admin-exporter', 'admin@example.com', 'password')
        Profile.objects.create(user=admin)
        report = DailyReport.objects.create(
            user=self.user,
            date=timezone.localdate(),
            role='dev',
            today_work='Async report content',
        )
        report.projects.add(self.project)
        job = _create_export_job(admin, 'admin_reports_filtered')

        path = generate_export_file_task.run(job.id, 'admin_reports_filtered', {
            'start_date': timezone.localdate().isoformat(),
            'end_date': timezone.localdate().isoformat(),
            'username': self.user.username,
            'project_id': str(self.project.id),
        })
        self.generated_files.append(path)

        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        with open(job.file_path, encoding='utf-8') as export_file:
            self.assertIn('Async report content', export_file.read())
