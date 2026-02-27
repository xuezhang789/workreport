
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from projects.models import Project
from unittest.mock import patch

User = get_user_model()

class ProjectSearchApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client = Client()
        self.client.login(username='testuser', password='password')
        
        self.p1 = Project.objects.create(name='Alpha Project', code='ALPHA', owner=self.user)
        self.p2 = Project.objects.create(name='Beta Project', code='BETA')
        self.url = reverse('projects:project_search_api')

    @patch('projects.views.get_accessible_projects')
    def test_search_api_lite_mode(self, mock_get_access):
        """Test lite mode returns correct fields."""
        # Mock permissions to return p1 and p2
        mock_get_access.return_value = Project.objects.filter(id__in=[self.p1.id, self.p2.id])
        
        response = self.client.get(self.url, {'mode': 'lite'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        results = data['results']
        self.assertEqual(len(results), 2)
        
        codes = sorted([r['code'] for r in results])
        self.assertEqual(codes, ['ALPHA', 'BETA'])
        self.assertIn('pinyin', results[0])

    @patch('projects.views.get_accessible_projects')
    def test_search_api_search(self, mock_get_access):
        """Test search filtering."""
        mock_get_access.return_value = Project.objects.filter(id__in=[self.p1.id, self.p2.id])
        
        response = self.client.get(self.url, {'q': 'Alpha'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['name'], 'Alpha Project')
