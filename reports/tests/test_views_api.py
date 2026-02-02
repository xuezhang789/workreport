import json

from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User

from projects.models import Project
from tasks.models import Task
from reports.views_api import api_project_detail, api_task_detail


class ReportsApiViewsTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_superuser(
            username='admin', password='pass', email='admin@example.com'
        )
        self.project = Project.objects.create(name='P3', code='P3', owner=self.user)
        self.task = Task.objects.create(
            title='Task API',
            user=self.user,
            project=self.project,
        )

    def test_api_project_detail(self):
        request = self.factory.get('/reports/api/project-detail/')
        request.user = self.user
        response = api_project_detail(request, self.project.id)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload['id'], self.project.id)

    def test_api_task_detail(self):
        request = self.factory.get('/reports/api/task-detail/')
        request.user = self.user
        response = api_task_detail(request, self.task.id)
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload['id'], self.task.id)
