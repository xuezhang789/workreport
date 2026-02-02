from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from reports.models import Project, Profile
from django.db import connection
from django.test.utils import CaptureQueriesContext

User = get_user_model()

class TeamsPerformanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('reports:teams')
        
        # Create superuser
        self.admin = User.objects.create_superuser(username='admin', password='password')
        
        # Create many projects
        self.projects = []
        for i in range(20):
            p = Project.objects.create(name=f'Project {i}', code=f'P{i}', is_active=True, owner=self.admin)
            self.projects.append(p)
            
        # Create many users and assign to projects
        self.users = []
        for i in range(50):
            u = User.objects.create_user(username=f'user{i}', password='password')
            # Create profile
            Profile.objects.create(user=u, position='dev')
            self.users.append(u)
            
            # Add to some projects
            project_idx = i % 20
            self.projects[project_idx].members.add(u)
            
    def test_teams_view_performance(self):
        self.client.force_login(self.admin)
        
        # Warmup
        self.client.get(self.url)
        
        print("\n--- Teams View Performance ---")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
            
        self.assertEqual(response.status_code, 200)
        print(f"Queries: {len(ctx.captured_queries)}")
        for q in ctx.captured_queries:
             print(f"SQL: {q['sql']}")
        
        # Verify pagination size in context (should be 28 currently)
        # We can't easily check paginator per_page from response context unless we inspect the paginator object
        # but we can check num_pages
        # 50 users + 1 admin = 51 users. 20 per page -> 3 pages.
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 3)
        
        # Verify Project Pagination
        # 20 projects. 20 per page -> 1 page.
        # Add more projects to test pagination
        for i in range(21):
             Project.objects.create(name=f'Extra Project {i}', code=f'EP{i}', is_active=True, owner=self.admin)
             
        # Now 41 projects. 20 per page -> 3 pages.
        response = self.client.get(self.url)
        self.assertEqual(response.context['project_page_obj'].paginator.num_pages, 3)
