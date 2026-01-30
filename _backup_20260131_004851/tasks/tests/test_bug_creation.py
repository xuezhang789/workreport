from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from tasks.models import Task
from core.constants import TaskCategory, TaskStatus
from projects.models import Project

class BugCreationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_superuser(
            username='admin', password='password'
        )
        self.client.login(username='admin', password='password')
        self.project = Project.objects.create(name='Test Project', owner=self.user, code='TEST')

    def test_create_page_bug_default_render(self):
        """
        Verify that accessing the create page with category=BUG renders status=NEW as selected.
        """
        url = reverse('tasks:admin_task_create')
        response = self.client.get(url, {'category': 'BUG'})
        self.assertEqual(response.status_code, 200)
        
        # Check context instead of raw HTML for robustness
        form_values = response.context['form_values']
        self.assertEqual(form_values['status'], TaskStatus.NEW)
        
        # Also verify it is NOT todo
        self.assertNotEqual(form_values['status'], TaskStatus.TODO)

    def test_create_bug_backend_correction(self):
        """
        Verify that submitting a BUG with empty status or 'todo' status defaults to NEW.
        """
        url = reverse('tasks:admin_task_create')
        
        # Case 1: Status 'todo' (invalid for BUG) -> Should become NEW
        data = {
            'title': 'Test Bug 1',
            'project': self.project.id,
            'user': self.user.id,
            'category': TaskCategory.BUG,
            'status': TaskStatus.TODO, # Invalid for bug
            'priority': 'medium',
            'content': 'Test Content'
        }
        response = self.client.post(url, data)
        if response.status_code != 302:
            print(response.context.get('errors'))
        self.assertEqual(response.status_code, 302) # Redirects on success
        
        task = Task.objects.get(title='Test Bug 1')
        self.assertEqual(task.category, TaskCategory.BUG)
        self.assertEqual(task.status, TaskStatus.NEW) # Corrected to NEW

        # Case 2: Status 'confirmed' (valid for BUG) -> Should remain CONFIRMED
        data2 = {
            'title': 'Test Bug 2',
            'project': self.project.id,
            'user': self.user.id,
            'category': TaskCategory.BUG,
            'status': TaskStatus.CONFIRMED,
            'priority': 'medium',
            'content': 'Test Content'
        }
        response = self.client.post(url, data2)
        if response.status_code != 302:
            print(response.context.get('errors'))
        task2 = Task.objects.get(title='Test Bug 2')
        self.assertEqual(task2.status, TaskStatus.CONFIRMED)

    def test_create_task_default(self):
        """
        Verify that creating a normal TASK defaults to TODO (or respects input).
        """
        url = reverse('tasks:admin_task_create')
        data = {
            'title': 'Test Task 1',
            'project': self.project.id,
            'user': self.user.id,
            'category': TaskCategory.TASK,
            'status': TaskStatus.TODO,
            'priority': 'medium',
            'content': 'Test Content'
        }
        response = self.client.post(url, data)
        task = Task.objects.get(title='Test Task 1')
        self.assertEqual(task.category, TaskCategory.TASK)
        self.assertEqual(task.status, TaskStatus.TODO)
