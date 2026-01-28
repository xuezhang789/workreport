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
            status='todo',
            created_at=timezone.now()
        )
        self.task2 = Task.objects.create(
            title='Task 2',
            project=self.project,
            user=self.user,
            status='done',
            created_at=timezone.now()
        )

    def test_project_detail_shows_tasks(self):
        self.client.force_login(self.user)
        response = self.client.get(f'/projects/{self.project.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '关联任务 / Tasks')
        self.assertContains(response, 'Task 1')
        self.assertContains(response, 'Task 2')
        
    def test_task_filtering(self):
        self.client.force_login(self.user)
        # Filter done
        response = self.client.get(f'/projects/{self.project.id}/?task_status=done')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Task 2')
        self.assertNotContains(response, 'Task 1') # Task 1 is todo
        
    def test_create_task_button_visibility(self):
        # Regular user (owner) should see create button if they have permission
        # In current logic, owner has manage permission?
        # Let's check permissions. Usually owner has manage permission.
        self.client.force_login(self.user)
        response = self.client.get(f'/projects/{self.project.id}/')
        # If user is owner, they can manage.
        self.assertContains(response, '+ 新建')
        
        # Another user (Member)
        other_user = User.objects.create_user('other', 'other@example.com', 'password')
        self.project.members.add(other_user) # Add as member so they can view project
        self.client.force_login(other_user)
        response = self.client.get(f'/projects/{self.project.id}/')
        self.assertEqual(response.status_code, 200)
        # Other user can view but not manage
        self.assertNotContains(response, '+ 新建')

