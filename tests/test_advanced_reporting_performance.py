from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from tasks.models import Task, TaskStatus
from projects.models import Project
from core.models import Profile
from django.db import connection
from django.test.utils import CaptureQueriesContext

User = get_user_model()

class AdvancedReportingPerformanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('reports:advanced_reporting')
        
        # Create superuser
        self.admin = User.objects.create_superuser(username='admin', password='password')
        
        # Create project
        self.project = Project.objects.create(name='Test Project', code='TP', is_active=True)
        
        # Create tasks (a reasonable number to test aggregation)
        now = timezone.now()
        tasks = []
        for i in range(100): # 100 tasks
            t = Task.objects.create(
                project=self.project,
                title=f'Task {i}',
                user=self.admin,
                status=TaskStatus.DONE if i % 2 == 0 else TaskStatus.TODO,
                created_at=now - timedelta(days=i % 30),
                completed_at=now if i % 2 == 0 else None,
                due_at=now + timedelta(days=1)
            )
            tasks.append(t)
            
    def test_performance(self):
        self.client.force_login(self.admin)
        
        # Warmup
        self.client.get(self.url)
        
        print("\n--- Advanced Reporting Performance ---")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
            
        self.assertEqual(response.status_code, 200)
        print(f"Queries: {len(ctx.captured_queries)}")
        
        # Test with project filter
        url_with_project = f"{self.url}?project_id={self.project.id}"
        self.client.get(url_with_project) # Warmup
        
        print("\n--- Advanced Reporting (Project Filter) Performance ---")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url_with_project)
            
        self.assertEqual(response.status_code, 200)
        print(f"Project Filter Queries: {len(ctx.captured_queries)}")
