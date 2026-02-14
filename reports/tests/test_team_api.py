from django.test import TestCase, Client
from django.contrib.auth.models import User
from core.models import Profile
from projects.models import Project
from django.urls import reverse
import json
from unittest.mock import patch

class TeamApiTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.user = User.objects.create_user('user', 'user@example.com', 'password')
        Profile.objects.create(user=self.user, position='dev')
        self.project = Project.objects.create(name="Test Project", code="TP", owner=self.admin)
        self.client = Client()

    @patch('reports.views_teams.get_channel_layer')
    @patch('reports.views_teams.async_to_sync')
    def test_update_role_api(self, mock_async_to_sync, mock_get_channel_layer):
        self.client.force_login(self.admin)
        url = reverse('reports:team_member_update_role', args=[self.user.id])
        
        # Test JSON response
        response = self.client.post(
            url, 
            {'role': 'pm'}, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.position, 'pm')
        
        # Verify Channel Layer call
        mock_get_channel_layer.assert_called()
        mock_async_to_sync.assert_called()

    @patch('reports.views_teams.get_channel_layer')
    @patch('reports.views_teams.async_to_sync')
    def test_add_project_api(self, mock_async_to_sync, mock_get_channel_layer):
        self.client.force_login(self.admin)
        url = reverse('reports:team_member_add_project', args=[self.user.id])
        
        response = self.client.post(
            url, 
            {'project_id': self.project.id}, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(len(data['projects']), 1)
        self.assertEqual(data['projects'][0]['id'], self.project.id)
        
        self.assertTrue(self.project.members.filter(id=self.user.id).exists())

    @patch('reports.views_teams.get_channel_layer')
    @patch('reports.views_teams.async_to_sync')
    def test_remove_project_api(self, mock_async_to_sync, mock_get_channel_layer):
        self.project.members.add(self.user)
        self.client.force_login(self.admin)
        
        url = reverse('reports:team_member_remove_project', args=[self.user.id, self.project.id])
        
        response = self.client.post(
            url, 
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(len(data['projects']), 0)
        
        self.assertFalse(self.project.members.filter(id=self.user.id).exists())
