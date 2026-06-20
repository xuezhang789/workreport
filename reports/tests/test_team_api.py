from django.test import TestCase, Client
from django.contrib.auth.models import User
from core.models import Profile
from audit.models import AuditLog
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
    def test_update_role_api_creates_missing_profile(self, mock_async_to_sync, mock_get_channel_layer):
        self.user.profile.delete()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('reports:team_member_update_role', args=[self.user.id]),
            {'role': 'qa'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        profile = Profile.objects.get(user=self.user)
        self.assertEqual(profile.position, 'qa')
        mock_get_channel_layer.assert_called_once()
        mock_async_to_sync.assert_called_once()

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
        self.assertEqual(data['available_projects'], [])
        
        self.assertTrue(self.project.members.filter(id=self.user.id).exists())
        self.assertTrue(AuditLog.objects.filter(
            summary=f'user_project_add {self.user.id} -> {self.project.id}'
        ).exists())

    def test_member_projects_api_separates_assigned_and_available_projects(self):
        available_project = Project.objects.create(
            name='Available Project',
            code='AVAILABLE',
            owner=self.admin,
        )
        self.project.members.add(self.user)
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse('reports:team_member_projects', args=[self.user.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([item['id'] for item in data['projects']], [self.project.id])
        self.assertEqual([item['id'] for item in data['available_projects']], [available_project.id])

    def test_project_manager_only_sees_projects_they_can_manage(self):
        manager = User.objects.create_user('manager', 'manager@example.com', 'password')
        managed_project = Project.objects.create(name='Managed', code='MANAGED', owner=manager)
        hidden_project = Project.objects.create(name='Hidden', code='HIDDEN', owner=self.admin)
        managed_project.members.add(self.user)
        hidden_project.members.add(self.user)
        self.client.force_login(manager)

        response = self.client.get(
            reverse('reports:team_member_projects', args=[self.user.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([item['id'] for item in data['projects']], [managed_project.id])
        self.assertNotIn(hidden_project.id, [item['id'] for item in data['projects']])
        self.assertNotIn(hidden_project.id, [item['id'] for item in data['available_projects']])

    def test_project_manager_cannot_add_member_to_unmanaged_project(self):
        manager = User.objects.create_user('limited-manager', 'limited@example.com', 'password')
        Project.objects.create(name='Managed', code='LIMITED', owner=manager)
        self.client.force_login(manager)

        response = self.client.post(
            reverse('reports:team_member_add_project', args=[self.user.id]),
            {'project_id': self.project.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['status'], 'error')
        self.assertFalse(self.project.members.filter(id=self.user.id).exists())

    def test_project_manager_page_hides_global_role_controls(self):
        manager = User.objects.create_user('page-manager', 'page-manager@example.com', 'password')
        Project.objects.create(name='Managed', code='PAGE-MANAGED', owner=manager)
        self.client.force_login(manager)

        response = self.client.get(reverse('reports:teams'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="umm-role-form"')
        self.assertContains(response, 'id="umm-project-select"')

    def test_add_project_rejects_inactive_project(self):
        self.project.is_active = False
        self.project.save(update_fields=['is_active'])
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('reports:team_member_add_project', args=[self.user.id]),
            {'project_id': self.project.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['status'], 'error')
        self.assertFalse(self.project.members.filter(id=self.user.id).exists())

    def test_add_project_rejects_duplicate_assignment(self):
        self.project.members.add(self.user)
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('reports:team_member_add_project', args=[self.user.id]),
            {'project_id': self.project.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('already in project', response.json()['message'])

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
