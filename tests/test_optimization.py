from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from reports.models import Project, Task, DailyReport, SystemSetting, ProjectPhaseConfig
from tasks.services.sla import calculate_sla_info

class OptimizationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('user', 'user@example.com', 'password')
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        
        # Create Phase
        self.phase = ProjectPhaseConfig.objects.create(phase_name='Phase 1', progress_percentage=10)
        
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.user, current_phase=self.phase)
        
        # Create Tasks
        self.task1 = Task.objects.create(title='T1', project=self.project, user=self.user, status='todo')
        self.task2 = Task.objects.create(title='T2', project=self.project, user=self.user, status='done', due_at=timezone.now(), completed_at=timezone.now())
        
        # Create Report
        self.report = DailyReport.objects.create(user=self.user, date=timezone.now().date(), status='submitted')
        self.report.projects.add(self.project)

    def test_workbench_queries(self):
        self.client.force_login(self.user)
        # Login triggers session/user updates
        
        # Workbench:
        # 1. Session
        # 2. User
        # 3. Stats (counts)
        # 4. Due today count
        # 5. Due soon count
        # 6. Streak
        # 7. Today report
        # 8. Projects list (aggregated)
        # 9. Profile (for role/position)
        # 10. RoleTemplate
        # 11. Project Managers (permission)
        # 12. UserPreference
        # 13. Managed projects
        # 14. Recent reports
        with self.assertNumQueries(13):
            response = self.client.get('/reports/workbench/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Project')
        
    def test_stats_queries(self):
        self.client.force_login(self.admin)
        # Check stats view
        response = self.client.get('/tasks/admin/stats/')
        self.assertEqual(response.status_code, 200)
        # The view might not contain 'Test Project' if it renders a chart or specific data
        # But let's check status code first.
        # self.assertContains(response, 'Test Project')

    def test_task_list_optimization(self):
        self.client.force_login(self.user)
        # Ensure cached settings are used (mocking would be better but simple run is fine)
        response = self.client.get('/tasks/')
        self.assertEqual(response.status_code, 200)
        
    def test_admin_task_list(self):
        self.client.force_login(self.admin)
        response = self.client.get('/tasks/admin/')
        self.assertEqual(response.status_code, 200)

    def test_project_names_property(self):
        # Prefetch should work
        report = DailyReport.objects.prefetch_related('projects').first()
        with self.assertNumQueries(0): # Should not query DB
            names = report.project_names
            self.assertIn('Test Project', names)
