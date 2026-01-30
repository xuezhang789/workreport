from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from tasks.models import Task
from projects.models import Project
from core.models import Profile
from core.constants import TaskStatus, TaskCategory
from tasks.services.state import TaskStateService

class TaskCategoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.project = Project.objects.create(name='Test Project', owner=self.user)
        self.client.force_login(self.user)

    def test_default_category(self):
        task = Task.objects.create(
            title='Default Task',
            project=self.project,
            user=self.user
        )
        self.assertEqual(task.category, TaskCategory.TASK)
        self.assertEqual(task.status, TaskStatus.TODO)

    def test_create_bug_model_default(self):
        # Test model save logic directly
        task = Task.objects.create(
            title='Direct Bug',
            project=self.project,
            user=self.user,
            category=TaskCategory.BUG
            # No status provided, should use default TODO then auto-correct to NEW
        )
        self.assertEqual(task.status, TaskStatus.NEW)
        
    def test_create_bug_view_default(self):
        # Test via View with empty status
        response = self.client.post(reverse('tasks:admin_task_create'), {
            'title': 'New Bug View',
            'project': self.project.id,
            'user': self.user.id,
            'category': TaskCategory.BUG,
            'status': '', # Empty status
            'priority': 'high',
            'content': 'Bug content'
        })
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title='New Bug View')
        self.assertEqual(task.status, TaskStatus.NEW)

    def test_create_bug_initial_status(self):
        # Test via View
        response = self.client.post(reverse('tasks:admin_task_create'), {
            'title': 'New Bug',
            'project': self.project.id,
            'user': self.user.id,
            'category': TaskCategory.BUG,
            'status': 'todo', # Should be ignored/overridden
            'priority': 'high',
            'content': 'Bug content'
        })
        self.assertEqual(response.status_code, 302)
        
        task = Task.objects.get(title='New Bug')
        self.assertEqual(task.category, TaskCategory.BUG)
        self.assertEqual(task.status, TaskStatus.NEW)

    def test_state_transitions_bug(self):
        # Create Bug
        task = Task.objects.create(
            title='Bug Flow',
            project=self.project,
            user=self.user,
            category=TaskCategory.BUG,
            status=TaskStatus.NEW
        )
        
        # Valid: New -> Confirmed
        self.assertTrue(TaskStateService.validate_transition(task.category, task.status, TaskStatus.CONFIRMED))
        
        # Invalid: New -> Closed
        self.assertFalse(TaskStateService.validate_transition(task.category, task.status, TaskStatus.CLOSED))
        
        # Invalid: New -> Todo (Task status)
        self.assertFalse(TaskStateService.validate_transition(task.category, task.status, TaskStatus.TODO))

    def test_state_transitions_task(self):
        task = Task.objects.create(
            title='Task Flow',
            project=self.project,
            user=self.user,
            category=TaskCategory.TASK,
            status=TaskStatus.TODO
        )
        
        # Valid: Todo -> In Progress
        self.assertTrue(TaskStateService.validate_transition(task.category, task.status, TaskStatus.IN_PROGRESS))
        
        # Valid: Todo -> Done (Task allows jumping)
        self.assertTrue(TaskStateService.validate_transition(task.category, task.status, TaskStatus.DONE))

    def test_view_status_update_validation(self):
        task = Task.objects.create(
            title='Bug Update',
            project=self.project,
            user=self.user,
            category=TaskCategory.BUG,
            status=TaskStatus.NEW
        )
        
        # Try invalid update via POST
        response = self.client.post(reverse('tasks:task_view', args=[task.id]), {
            'action': 'set_status',
            'status_value': TaskStatus.CLOSED # Invalid from NEW
        })
        self.assertEqual(response.status_code, 302)
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.NEW)
        
        # Valid update
        response = self.client.post(reverse('tasks:task_view', args=[task.id]), {
            'action': 'set_status',
            'status_value': TaskStatus.CONFIRMED
        })
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.CONFIRMED)

    def test_list_filtering(self):
        Task.objects.create(title='T1', project=self.project, user=self.user, category=TaskCategory.TASK)
        Task.objects.create(title='B1', project=self.project, user=self.user, category=TaskCategory.BUG)
        
        response = self.client.get(reverse('tasks:task_list'), {'category': 'BUG'})
        self.assertContains(response, 'B1')
        self.assertNotContains(response, 'T1')
        
        response = self.client.get(reverse('tasks:task_list'), {'category': 'TASK'})
        self.assertContains(response, 'T1')
        self.assertNotContains(response, 'B1')
