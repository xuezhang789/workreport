from django.test import TestCase, Client
from django.contrib.auth.models import User
from reports.models import Project, Profile
from django.urls import reverse
from django.utils import timezone

class ProjectEditPermissionTest(TestCase):
    def setUp(self):
        # Users
        self.superuser = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'password')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'password')
        self.member = User.objects.create_user('member', 'member@example.com', 'password')
        self.other = User.objects.create_user('other', 'other@example.com', 'password')

        # Project
        self.project = Project.objects.create(
            name="Test Project",
            code="TP-001",
            owner=self.owner,
            is_active=True
        )
        self.project.managers.add(self.manager)
        self.project.members.add(self.member)

        self.client = Client()
        self.url = reverse('reports:project_edit', args=[self.project.id])

    def test_superuser_full_access(self):
        self.client.force_login(self.superuser)
        
        # GET: All editable
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['can_edit_owner'])
        self.assertTrue(response.context['can_edit_managers'])

        # POST: Change Owner and Managers
        response = self.client.post(self.url, {
            'name': 'Updated by Admin',
            'code': 'TP-001',
            'owner': self.other.id,
            'managers': [self.member.id],
            'members': [],
            'is_active': 'on'
        })
        self.assertEqual(response.status_code, 302)
        
        self.project.refresh_from_db()
        self.assertEqual(self.project.owner, self.other)
        self.assertTrue(self.project.managers.filter(id=self.member.id).exists())

    def test_owner_restricted_access(self):
        self.client.force_login(self.owner)
        
        # GET: Owner read-only, Managers editable
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['can_edit_owner'])
        self.assertTrue(response.context['can_edit_managers'])

        # POST: Try to change Owner (should fail/ignore)
        # In our implementation, disabled fields are ignored by Django form if disabled in view.
        # But if we hacked the POST request to include it?
        # Django's form processing for disabled fields: "A disabled field’s value in cleaned_data will match the initial value"
        # So it should silently ignore the change.
        
        response = self.client.post(self.url, {
            'name': 'Updated by Owner',
            'code': 'TP-001',
            'owner': self.other.id, # Attempt to change
            'managers': [self.member.id], # Change managers (Allowed)
            'members': [],
            'is_active': 'on'
        })
        self.assertEqual(response.status_code, 302)
        
        self.project.refresh_from_db()
        self.assertEqual(self.project.owner, self.owner) # Should remain Owner
        self.assertEqual(self.project.name, 'Updated by Owner')
        self.assertTrue(self.project.managers.filter(id=self.member.id).exists()) # Managers changed

    def test_manager_restricted_access(self):
        self.client.force_login(self.manager)
        
        # GET: Owner read-only, Managers read-only
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['can_edit_owner'])
        self.assertFalse(response.context['can_edit_managers'])

        # POST: Try to change Owner and Managers (should fail/ignore)
        response = self.client.post(self.url, {
            'name': 'Updated by Manager',
            'code': 'TP-001',
            'owner': self.other.id, # Attempt to change
            'managers': [self.other.id], # Attempt to change
            'members': [self.other.id], # Change members (Allowed)
            'is_active': 'on'
        })
        self.assertEqual(response.status_code, 302)
        
        self.project.refresh_from_db()
        self.assertEqual(self.project.owner, self.owner) # Unchanged
        self.assertTrue(self.project.managers.filter(id=self.manager.id).exists()) # Unchanged (Original manager)
        self.assertFalse(self.project.managers.filter(id=self.other.id).exists())
        self.assertTrue(self.project.members.filter(id=self.other.id).exists()) # Members changed
        self.assertEqual(self.project.name, 'Updated by Manager')

    def test_unauthorized_access(self):
        self.client.force_login(self.other)
        response = self.client.get(self.url)
        # Should be 403 because of can_manage_project check
        self.assertEqual(response.status_code, 403)
