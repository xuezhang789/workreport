from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from projects.models import Project
from tasks.models import Task

class CommandPaletteApiTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client = Client()
        self.client.force_login(self.user)
        
        # Create Data
        self.project = Project.objects.create(name="Alpha Project", code="ALPHA", owner=self.user)
        self.task = Task.objects.create(title="Fix Bug 123", project=self.project, user=self.user)
        
    def test_search_project(self):
        url = reverse('core:command_search_api')
        response = self.client.get(url, {'q': 'Alpha'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Should find 1 project
        found = False
        for res in data['results']:
            if res['category'] == '项目 / Projects' and 'Alpha' in res['title']:
                found = True
                break
        self.assertTrue(found, "Should find Alpha Project")

    def test_search_task(self):
        url = reverse('core:command_search_api')
        response = self.client.get(url, {'q': 'Bug 123'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        found = False
        for res in data['results']:
            if res['category'] == '任务 / Tasks' and 'Fix Bug' in res['title']:
                found = True
                break
        self.assertTrue(found, "Should find Task Fix Bug")
        
    def test_search_action(self):
        url = reverse('core:command_search_api')
        response = self.client.get(url, {'q': 'new task'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        found = False
        for res in data['results']:
            if res['category'] == '操作 / Actions' and 'New Task' in res['title']:
                found = True
                break
        self.assertTrue(found, "Should find New Task action")

    def test_empty_query(self):
        url = reverse('core:command_search_api')
        response = self.client.get(url, {'q': ''})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['results']), 0)
