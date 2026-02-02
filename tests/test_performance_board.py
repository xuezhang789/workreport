from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from tasks.models import Task, TaskStatus
from projects.models import Project
from core.models import Profile, SystemSetting
from django.db import connection
from django.test.utils import CaptureQueriesContext

User = get_user_model()

class PerformanceBoardTest(TestCase):
    def setUp(self):
        self.client = Client()
        # The URL for performance board
        self.url = reverse('reports:performance_board')
        
        # Create superuser
        self.admin = User.objects.create_superuser(username='admin', password='password')
        
        # Create system settings for SLA
        SystemSetting.objects.create(key='sla_hours', value='24')
        SystemSetting.objects.create(key='sla_thresholds', value='4,8')
        
        # Create projects
        self.projects = []
        for i in range(5):
            p = Project.objects.create(name=f'Project {i}', code=f'P{i}', is_active=True)
            self.projects.append(p)
            
        # Create users
        self.users = []
        for i in range(10):
            u = User.objects.create_user(username=f'user{i}', password='password')
            Profile.objects.create(user=u, position='dev')
            self.users.append(u)
            
        # Create tasks
        now = timezone.now()
        tasks = []
        # Create 200 tasks
        for i in range(200):
            project = self.projects[i % 5]
            user = self.users[i % 10]
            status = TaskStatus.DONE if i % 2 == 0 else TaskStatus.TODO
            created_at = now - timedelta(days=i % 30 + 1)
            completed_at = now if status == TaskStatus.DONE else None
            
            t = Task(
                project=project,
                title=f'Task {i}',
                user=user,
                status=status,
                created_at=created_at,
                completed_at=completed_at,
                due_at=now + timedelta(days=1)
            )
            tasks.append(t)
        Task.objects.bulk_create(tasks)
            
    def test_performance(self):
        self.client.force_login(self.admin)
        
        # Warmup
        self.client.get(self.url)
        
        print("\n--- Performance Board Stats ---")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
            
        self.assertEqual(response.status_code, 200)
        print(f"Queries: {len(ctx.captured_queries)}")
        # for q in ctx.captured_queries:
        #     print(f"SQL: {q['sql']}")
