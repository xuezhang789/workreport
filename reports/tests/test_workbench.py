from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from tasks.models import Task
from projects.models import Project
from work_logs.models import DailyReport
from core.models import Profile

User = get_user_model()

class WorkbenchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.profile = Profile.objects.create(user=self.user, position='dev')
        self.client.login(username='testuser', password='password')
        
        self.project = Project.objects.create(
            name='Test Project',
            code='TP',
            owner=self.user,
            is_active=True
        )
        
        # Create some tasks
        Task.objects.create(
            title='Task 1',
            project=self.project,
            user=self.user,
            status='todo',
            priority='high',
            due_at=timezone.now() + timedelta(days=1)
        )
        Task.objects.create(
            title='Task 2',
            project=self.project,
            user=self.user,
            status='done',
            priority='medium'
        )
        
        # Create a report
        DailyReport.objects.create(
            user=self.user,
            date=timezone.localdate(),
            today_work='Worked on Task 1',
            status='submitted'
        )

    def test_workbench_main_view(self):
        """Test the skeleton view loads"""
        response = self.client.get(reverse('reports:workbench'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/workbench_v2.html')

    def test_workbench_stats_partial(self):
        """Test the stats partial"""
        response = self.client.get(reverse('reports:workbench_stats'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/partials/workbench_stats.html')
        self.assertIn('stats', response.context)
        self.assertEqual(response.context['stats']['total'], 2)
        self.assertEqual(response.context['stats']['completed'], 1)
        self.assertTrue(response.context['has_today_report'])

    def test_workbench_tasks_partial(self):
        """Test the tasks partial"""
        response = self.client.get(reverse('reports:workbench_tasks'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/partials/workbench_tasks.html')
        self.assertIn('my_tasks', response.context)
        # Should only show non-done tasks
        self.assertEqual(len(response.context['my_tasks']), 1)
        self.assertEqual(response.context['my_tasks'][0].title, 'Task 1')

    def test_workbench_projects_partial(self):
        """Test the projects partial"""
        response = self.client.get(reverse('reports:workbench_projects'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/partials/workbench_projects.html')
        self.assertIn('project_burndown', response.context)
        self.assertEqual(len(response.context['project_burndown']), 1)
        self.assertEqual(response.context['project_burndown'][0]['total'], 2)

    def test_workbench_reports_partial(self):
        """Test the reports partial"""
        response = self.client.get(reverse('reports:workbench_reports'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/partials/workbench_reports.html')
        self.assertIn('recent_reports', response.context)
        self.assertEqual(len(response.context['recent_reports']), 1)
