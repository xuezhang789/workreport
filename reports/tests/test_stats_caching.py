from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from core.models import Profile, SystemSetting
from projects.models import Project
from tasks.models import Task
from core.constants import TaskStatus
import json
from unittest.mock import patch

class StatsCachingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin', password='password', is_superuser=True)
        self.client = Client()
        self.client.force_login(self.user)
        Profile.objects.create(user=self.user, position='mgr')
        
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.user, is_active=True)
        
        # Create some tasks
        for i in range(5):
            Task.objects.create(
                title=f'Task {i}',
                user=self.user,
                project=self.project,
                status=TaskStatus.TODO,
                due_at=timezone.now() + timezone.timedelta(hours=1)
            )
            
        # SLA Settings
        SystemSetting.objects.create(key='sla_hours', value='24')
        SystemSetting.objects.create(key='sla_thresholds', value=json.dumps({"amber": 4, "red": 1}))

    def test_stats_view_sla_caching(self):
        """Test that stats view caches SLA urgent tasks."""
        url = reverse('reports:stats')
        
        # Clear cache
        cache.clear()
        
        # First request - Should set cache
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Check if cache is set
        # Key pattern: stats_sla_urgent_v1_{date}_{project}_{role}
        today = timezone.localdate()
        # project_filter is None if not in GET, role_filter is '' if not in GET
        # f"{None}" is "None"
        key = f"stats_sla_urgent_v1_{today}_None_"
        
        cached_data = cache.get(key)
        self.assertIsNotNone(cached_data, "Cache should be set after first request")
        self.assertEqual(len(cached_data), 5, "Should cache 5 urgent tasks")
        
        # Modify data in DB (delete a task)
        # Prevent cache invalidation to test if view uses existing cache
        with patch('reports.signals._invalidate_stats_cache'):
            Task.objects.first().delete()
        
        # Second request - Should use cache (still 5 tasks)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        cached_data_2 = cache.get(key)
        self.assertEqual(len(cached_data_2), 5, "Cache should persist and not reflect DB change immediately")
        
        # Clear cache and request again - Should reflect DB change (4 tasks)
        cache.delete(key)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        cached_data_3 = cache.get(key)
        self.assertEqual(len(cached_data_3), 4, "After cache clear, should reflect DB state")

    def test_admin_task_stats_caching(self):
        """Test that admin_task_stats caches the heavy calculation."""
        url = reverse('tasks:admin_task_stats')
        
        # Clear cache
        cache.clear()
        
        # First request
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        
        # Check cache
        # Key pattern: admin_task_stats_data_v3_{uid}_{period}_{start}_{end}_{pid}_{uid_filter}_{role}_{q}
        # Defaults: period='month'
        today = timezone.localdate()
        start_date = today.replace(day=1)
        end_date = today
        
        # Construct key exactly as in view
        # project_id, user_id, role, q are all None or empty strings in view when not provided
        # In view: 
        # project_filter = int(project_param) if ... else None
        # role_filter = role_param if ... else None
        # So they are None in the f-string, which becomes "None"
        
        key = f"admin_task_stats_data_v3_{self.user.id}_month_{start_date}_{end_date}_None_None_None_"
        
        cached_data = cache.get(key)
        self.assertIsNotNone(cached_data, f"Cache key {key} not found")
        self.assertEqual(cached_data['metric_new'], 5)
        
        # Modify DB but PREVENT cache invalidation to test if view uses cache
        # In tests, _invalidate_stats_cache usually calls cache.clear() which wipes everything.
        # We want to ensure the view logic uses the EXISTING cache if present.
        with patch('reports.signals._invalidate_stats_cache'):
            Task.objects.create(
                title='New Task',
                user=self.user,
                project=self.project,
                status=TaskStatus.TODO
            )
        
        # Second request - Should use cache (still 5)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['kpi']['new'], 5)
        
        # Clear cache
        cache.delete(key)
        
        # Third request - Should update (6)
        response = self.client.get(url)
        self.assertEqual(response.context['kpi']['new'], 6)
