import time
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from projects.models import Project
from core.models import Profile

class SearchFixTests(TestCase):
    def setUp(self):
        self.u_admin = User.objects.create_superuser('admin', 'admin@test.com', 'pass')
        self.u_user1 = User.objects.create_user('user1', 'user1@example.com', 'pass')
        self.u_user2 = User.objects.create_user('user2', 'user2@example.com', 'pass')
        
        Profile.objects.create(user=self.u_user1, position='dev')
        Profile.objects.create(user=self.u_user2, position='dev')

        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.u_admin)
        self.project.members.add(self.u_user1, self.u_user2)
        
        self.client = Client()

    def test_user_search_by_email(self):
        self.client.force_login(self.u_admin)
        url = reverse('core:user_search_api')
        
        # Search by partial email
        resp = self.client.get(url, {'q': 'user1@'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['username'], 'user1')
        self.assertIn('user1@example.com', data['results'][0]['text'])

    def test_user_search_throttle_relaxed(self):
        self.client.force_login(self.u_admin)
        url = reverse('core:user_search_api')
        
        # First request
        resp1 = self.client.get(url, {'q': 'u'})
        self.assertEqual(resp1.status_code, 200)
        
        # Wait > 0.2s
        time.sleep(0.25)
        resp3 = self.client.get(url, {'q': 'use'})
        self.assertEqual(resp3.status_code, 200)

    def test_project_search_throttle_relaxed(self):
        self.client.force_login(self.u_admin)
        url = reverse('projects:project_search_api')
        
        resp1 = self.client.get(url, {'q': 'Test'})
        self.assertEqual(resp1.status_code, 200)
        
        time.sleep(0.25)
        resp2 = self.client.get(url, {'q': 'Test P'})
        self.assertEqual(resp2.status_code, 200)
