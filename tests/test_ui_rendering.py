from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from reports.models import Project, Profile

class UIRenderingTests(TestCase):
    def setUp(self):
        # Create a user and log in
        self.user = User.objects.create_user(username='testuser', password='password')
        self.user.is_staff = True 
        self.user.is_superuser = True # Ensure superuser for teams list
        self.user.save()
        Profile.objects.create(user=self.user, position='dev')
        
        self.client = Client()
        self.client.login(username='testuser', password='password')
        
        # Create some data
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.user)

    def test_teams_page_renders(self):
        """Test that the teams page renders correctly with the new structure."""
        response = self.client.get(reverse('reports:teams'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/teams.html')
        # Check for new CSS classes/structure
        self.assertContains(response, 'team-grid')
        self.assertContains(response, 'team-card')
        # Check content
        self.assertContains(response, 'Test Project') # Project tag in user card

    def test_task_stats_page_renders(self):
        """Test that the task stats page renders correctly with the new structure."""
        response = self.client.get(reverse('tasks:admin_task_stats'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tasks/admin_task_stats.html')
        # Check for new CSS classes
        self.assertContains(response, 'kpi-row') # Updated from dashboard-grid
        self.assertContains(response, 'kpi-card') # Updated from kpi-card
        self.assertContains(response, 'table-tabs')
