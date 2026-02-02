from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from work_logs.models import DailyReport
from projects.models import Project
from core.models import Profile
from datetime import date, timedelta
from django.db import connection
from django.test.utils import CaptureQueriesContext
from core.models import Permission, Role, UserRole

User = get_user_model()

class AdminReportsPerformanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('reports:admin_reports')
        
        # Setup RBAC
        self.perm_view = Permission.objects.create(code='project.view', name='View Project')
        self.role_viewer = Role.objects.create(code='viewer', name='Viewer')
        self.role_viewer.permissions.add(self.perm_view)
        
        # Create superuser
        self.admin = User.objects.create_superuser(username='admin', password='password')
        
        # Create normal user with some permissions (manager)
        self.manager = User.objects.create_user(username='manager', password='password')
        Profile.objects.create(user=self.manager, position='mgr')
        
        # Create projects
        self.projects = []
        for i in range(5):
            p = Project.objects.create(name=f'Project {i}', code=f'P{i}', is_active=True)
            self.projects.append(p)
            # Assign view permission to manager for all projects
            UserRole.objects.create(user=self.manager, role=self.role_viewer, scope=f'project:{p.id}')
            
        # Create many users and reports
        self.users = []
        for i in range(10):
            u = User.objects.create_user(username=f'user{i}', password='password')
            Profile.objects.create(user=u, position='dev')
            self.users.append(u)
            
        # Create reports
        reports = []
        base_date = date.today()
        for i in range(50): # 50 reports
            u = self.users[i % 10]
            # Vary date for each user to avoid unique constraint
            # Each user gets 5 reports on different days
            r_date = base_date - timedelta(days=i // 10)
            
            r = DailyReport.objects.create(
                user=u,
                date=r_date,
                role='dev',
                status='submitted' if i % 2 == 0 else 'draft',
                today_work=f'Work {i}'
            )
            r.projects.add(self.projects[i % 5])
            reports.append(r)
            
    def test_admin_reports_performance(self):
        self.client.force_login(self.admin)
        
        # Warmup
        self.client.get(self.url)
        
        print("\n--- Superuser Performance ---")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
            
        self.assertEqual(response.status_code, 200)
        print(f"Superuser Queries: {len(ctx.captured_queries)}")
        
        self.client.logout()
        self.client.force_login(self.manager)
        
        # Warmup
        self.client.get(self.url)
        
        print("\n--- Manager Performance ---")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
            
        self.assertEqual(response.status_code, 200)
        print(f"Manager Queries: {len(ctx.captured_queries)}")
