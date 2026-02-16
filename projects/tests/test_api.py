from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from projects.models import Project

User = get_user_model()

class ResponsibleProjectsApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_a = User.objects.create_user(username='user_a', password='password')
        self.user_b = User.objects.create_user(username='user_b', password='password')
        self.superuser = User.objects.create_superuser(username='admin', password='password')
        
        # Project 1: User A is owner
        self.p1 = Project.objects.create(name='A_Project', code='P1', owner=self.user_a, is_active=True)
        
        # Project 2: User A is manager
        self.p2 = Project.objects.create(name='B_Project', code='P2', owner=self.user_b, is_active=True)
        self.p2.managers.add(self.user_a)
        
        # Project 3: User A is member (not responsible)
        self.p3 = Project.objects.create(name='C_Project', code='P3', owner=self.user_b, is_active=True)
        self.p3.members.add(self.user_a)
        
        # Project 4: User A has no relation
        self.p4 = Project.objects.create(name='D_Project', code='P4', owner=self.user_b, is_active=True)
        
        # Project 5: Inactive (User A is owner)
        self.p5 = Project.objects.create(name='E_Project', code='P5', owner=self.user_a, is_active=False)

    def test_unauthenticated(self):
        url = f'/api/v1/users/{self.user_a.id}/responsible-projects'
        response = self.client.get(url)
        self.assertNotEqual(response.status_code, 200)

    def test_permission_denied_other_user(self):
        self.client.force_login(self.user_b)
        url = f'/api/v1/users/{self.user_a.id}/responsible-projects'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_permission_allowed_self(self):
        self.client.force_login(self.user_a)
        url = f'/api/v1/users/{self.user_a.id}/responsible-projects'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(len(data), 2)
        
        # Verify P1 (Owner) and P2 (Manager) are present
        p_ids = [p['projectId'] for p in data]
        self.assertIn(self.p1.id, p_ids)
        self.assertIn(self.p2.id, p_ids)
        
        # Verify P3 (Member), P4 (None), P5 (Inactive) are NOT present
        self.assertNotIn(self.p3.id, p_ids)
        self.assertNotIn(self.p4.id, p_ids)
        self.assertNotIn(self.p5.id, p_ids)
        
        # Verify Sorting (A_Project before B_Project)
        self.assertEqual(data[0]['projectName'], 'A_Project')
        self.assertEqual(data[1]['projectName'], 'B_Project')
        
        # Verify Format and New Fields
        item = data[0]
        self.assertIn('projectId', item)
        self.assertIn('projectName', item)
        self.assertIn('projectCode', item)
        self.assertIn('ownerName', item)
        self.assertIn('phase', item)
        self.assertIn('progress', item)
        self.assertIn('isActive', item)
        
        # Verify specific values for P1 (A_Project)
        self.assertEqual(item['ownerName'], self.user_a.username) # get_full_name is empty in test user
        self.assertEqual(item['isActive'], True)
        # phase and progress might be empty/default, which is fine, just checking existence

    def test_permission_allowed_superuser(self):
        self.client.force_login(self.superuser)
        url = f'/api/v1/users/{self.user_a.id}/responsible-projects'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
