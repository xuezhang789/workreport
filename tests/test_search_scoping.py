
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from projects.models import Project
from core.models import Profile

User = get_user_model()

class UserSearchScopingTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create users
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'pass')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'pass')
        self.member = User.objects.create_user('member', 'member@example.com', 'pass')
        self.outsider = User.objects.create_user('outsider', 'outsider@example.com', 'pass')
        
        # Create profiles (required for search API to avoid errors)
        Profile.objects.create(user=self.owner)
        Profile.objects.create(user=self.manager)
        Profile.objects.create(user=self.member)
        Profile.objects.create(user=self.outsider)
        
        # Create project
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.owner)
        self.project.managers.add(self.manager)
        self.project.members.add(self.member)
        
        self.url = reverse('core:user_search_api')

    def test_search_scoped_to_project(self):
        """Test search with project_id returns only project related users."""
        self.client.force_login(self.owner)
        
        # Search with project_id
        resp = self.client.get(self.url, {'project_id': self.project.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        usernames = [u['username'] for u in data['results']]
        
        # Should include owner, manager, member
        self.assertIn('owner', usernames)
        self.assertIn('manager', usernames)
        self.assertIn('member', usernames)
        
        # Should NOT include outsider
        self.assertNotIn('outsider', usernames)
        
    def test_search_scoped_with_query(self):
        """Test search with project_id AND query string."""
        self.client.force_login(self.owner)
        
        # Search for 'member' inside project
        resp = self.client.get(self.url, {'project_id': self.project.id, 'q': 'mem'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        
        usernames = [u['username'] for u in data['results']]
        self.assertIn('member', usernames)
        self.assertNotIn('owner', usernames)
        self.assertNotIn('outsider', usernames)

    def test_search_permission_denied(self):
        """Test non-member cannot search project users if not accessible."""
        self.client.force_login(self.outsider)
        
        resp = self.client.get(self.url, {'project_id': self.project.id})
        # Expect 403 because outsider has no access to project
        self.assertEqual(resp.status_code, 403)

    def test_search_role_labels(self):
        """Test if API returns correct role labels."""
        self.client.force_login(self.owner)
        
        resp = self.client.get(self.url, {'project_id': self.project.id})
        data = resp.json()
        
        user_map = {u['username']: u['role'] for u in data['results']}
        
        self.assertEqual(user_map['owner'], 'Owner')
        self.assertEqual(user_map['manager'], 'Admin')
        self.assertEqual(user_map['member'], 'Member')
