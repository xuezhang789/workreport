
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model
from tasks.models import Task
from projects.models import Project
from core.models import SystemSetting
from core.constants import TaskStatus
from datetime import timedelta

User = get_user_model()

class MyTasksPerformanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password', is_superuser=True)
        self.client.force_login(self.user)
        
        # Create a project
        self.project = Project.objects.create(name='Test Project', owner=self.user, code='TEST')
        self.project.members.add(self.user)
        
        # Create SLA settings
        SystemSetting.objects.create(key='sla_hours', value='24')
        SystemSetting.objects.create(key='sla_thresholds', value='{"amber": 4, "red": 2}')
        
        # Create tasks
        now = timezone.now()
        tasks = []
        for i in range(50):
            tasks.append(Task(
                title=f'Task {i}',
                project=self.project,
                user=self.user,
                status=TaskStatus.TODO,
                due_at=now + timedelta(hours=10) # Due soon
            ))
        Task.objects.bulk_create(tasks)
        
        # Create tasks that are not due soon
        tasks_ok = []
        for i in range(50):
            tasks_ok.append(Task(
                title=f'Task OK {i}',
                project=self.project,
                user=self.user,
                status=TaskStatus.TODO,
                due_at=now + timedelta(hours=100)
            ))
        Task.objects.bulk_create(tasks_ok)

    def test_my_tasks_query_count(self):
        url = reverse('tasks:task_list')
        
        # Warm up
        self.client.get(url)
        
        # Current expected queries:
        # 1. SystemSetting (sla_hours)
        # 2. SystemSetting (sla_thresholds)
        # 3. due_soon_ids (SELECT id FROM task WHERE ...) - Heavy if many tasks
        # 4. Count for Paginator (SELECT COUNT(*) FROM task ...)
        # 5. Page Data (SELECT ... FROM task ...)
        # 6. Prefetch collaborators
        # 7. Projects list (SELECT ... FROM project ...)
        # 8. User query (session/auth)? - usually cached or 1 extra
        # 9. Accessible projects?
        
        # Expect 12 queries
        with self.assertNumQueries(12): 
            response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['tasks']), 20)
        self.assertEqual(response.context['due_soon_count'], 50)
