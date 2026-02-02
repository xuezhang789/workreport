from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from tasks.models import Task, TaskStatus
from projects.models import Project
from core.models import Profile, Permission, Role, UserRole
from django.db import connection
from django.test.utils import CaptureQueriesContext

User = get_user_model()

class AdminTaskStatsPerformanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('tasks:admin_task_stats')
        
        # Setup RBAC
        self.perm_view = Permission.objects.create(code='project.view', name='View Project')
        self.role_viewer = Role.objects.create(code='viewer', name='Viewer')
        self.role_viewer.permissions.add(self.perm_view)

        # Create superuser
        self.admin = User.objects.create_superuser(username='admin', password='password')
        
        # Create normal user
        self.manager = User.objects.create_user(username='manager', password='password')
        Profile.objects.create(user=self.manager, position='mgr')
        
        # Create project and assign permission
        self.project = Project.objects.create(name='Test Project', code='TP', is_active=True)
        UserRole.objects.create(user=self.manager, role=self.role_viewer, scope=f'project:{self.project.id}')

        # Create tasks
        now = timezone.now()
        tasks = []
        for i in range(50):
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
        
        print("\n--- Admin Task Stats Performance ---")
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.url)
            
        self.assertEqual(response.status_code, 200)
        print(f"Queries: {len(ctx.captured_queries)}")
        # for q in ctx.captured_queries:
        #     print(q['sql'])
