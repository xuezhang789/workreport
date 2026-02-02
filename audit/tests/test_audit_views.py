from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from projects.models import Project
from tasks.models import Task

User = get_user_model()

class AuditViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='testuser', password='password')
        self.client.force_login(self.user)
        self.project = Project.objects.create(name='Test Project', code='TP1', owner=self.user)
        self.task = Task.objects.create(title='Test Task', project=self.project, user=self.user)

    def test_project_history_view(self):
        url = reverse('projects:project_history', args=[self.project.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/project_history.html')
        self.assertTemplateUsed(response, 'audit/timeline.html')

    def test_task_history_view(self):
        url = reverse('tasks:task_history', args=[self.task.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tasks/task_history.html')
        self.assertTemplateUsed(response, 'audit/timeline.html')
