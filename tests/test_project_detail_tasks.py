from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from reports.models import Project, Task, ProjectPhaseConfig

class ProjectDetailTaskTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('user', 'user@example.com', 'password')
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        
        # Create a phase
        self.phase = ProjectPhaseConfig.objects.create(phase_name='Phase 1', progress_percentage=10)
        
        self.project = Project.objects.create(
            name='Test Project',
            code='TP-001',
            owner=self.user,
            current_phase=self.phase
        )
        
        # Create tasks
        self.task1 = Task.objects.create(
            title='Task 1',
            project=self.project,
            user=self.user,
            status='pending',
            created_at=timezone.now()
        )
        self.task2 = Task.objects.create(
            title='Task 2',
            project=self.project,
            user=self.user,
            status='completed',
            created_at=timezone.now()
        )

    def test_project_detail_shows_tasks(self):
        self.client.force_login(self.user)
        response = self.client.get(f'/reports/projects/{self.project.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '关联任务 / Tasks')
        self.assertContains(response, 'Task 1')
        self.assertContains(response, 'Task 2')
        
    def test_task_filtering(self):
        self.client.force_login(self.user)
        # Filter completed
        response = self.client.get(f'/reports/projects/{self.project.id}/?task_status=completed')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Task 2')
        self.assertNotContains(response, 'Task 1') # Task 1 is pending
        
    def test_create_task_button_visibility(self):
        # Regular user (owner) should see create button if they have permission
        # In current logic, owner has manage permission?
        # Let's check permissions. Usually owner has manage permission.
        self.client.force_login(self.user)
        response = self.client.get(f'/reports/projects/{self.project.id}/')
        # If user is owner, they can manage.
        self.assertContains(response, '+ 新建')
        
        # Another user
        other_user = User.objects.create_user('other', 'other@example.com', 'password')
        self.client.force_login(other_user)
        response = self.client.get(f'/reports/projects/{self.project.id}/')
        # Other user can view but not manage (unless added as member, but strictly manage logic usually restricts)
        # Assuming defaults, they might not even see the project if private?
        # But let's assume public or they have access.
        # If they can see it, they shouldn't see "Create Task" if they don't have manage permission.
        self.assertNotContains(response, '+ 新建')

