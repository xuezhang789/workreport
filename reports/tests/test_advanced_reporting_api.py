from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import ReportJob
from projects.models import Project
from tasks.models import Task
from django.utils import timezone
from datetime import timedelta
import json
import time

User = get_user_model()

from unittest.mock import patch
from django.test import TransactionTestCase

class AdvancedReportingAPITest(TransactionTestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(username='admin', password='password')
        self.client.force_login(self.user)
        
        # Create test data
        self.project = Project.objects.create(name="Test Project", owner=self.user, code="TEST")
        
        # Create 50 tasks for pagination testing
        for i in range(50):
            Task.objects.create(
                project=self.project,
                title=f"Task {i}",
                user=self.user,
                due_at=timezone.now() + timedelta(days=5),
                status='in_progress'
            )

    def test_gantt_pagination(self):
        """Test Gantt chart API pagination"""
        url = reverse('reports:api_advanced_gantt')
        
        # Test page 1, limit 20
        response = self.client.get(url, {'page': 1, 'limit': 20})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['total'], 50)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['limit'], 20)
        self.assertEqual(len(data['data']), 20)
        
        # Test page 3, limit 20 (should have 10 items)
        response = self.client.get(url, {'page': 3, 'limit': 20})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['data']), 10)

    @patch('reports.views_api.threading.Thread')
    def test_report_job_lifecycle(self, mock_thread):
        """Test the async report job lifecycle (Start -> Pending -> Check -> Done)"""
        # Mock thread to run target immediately
        def side_effect(target, args, daemon):
            target(*args)
            return type('MockThread', (), {'start': lambda: None})
        
        mock_thread.side_effect = side_effect

        # 1. Start a job
        start_url = reverse('reports:api_start_report_job')
        response = self.client.post(start_url, 
                                  json.dumps({'report_type': 'burndown'}),
                                  content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        start_data = response.json()
        job_id = start_data['job_id']
        
        # 2. Check status immediately
        check_url = reverse('reports:api_check_report_job', kwargs={'job_id': job_id})
        response = self.client.get(check_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'done')

    @patch('reports.views_api.threading.Thread')
    def test_caching_mechanism(self, mock_thread):
        """Test that subsequent requests for the same job return cached/db results"""
        # Mock thread to run target immediately
        def side_effect(target, args, daemon):
            target(*args)
            return type('MockThread', (), {'start': lambda: None})
        
        mock_thread.side_effect = side_effect

        # Start a job
        start_url = reverse('reports:api_start_report_job')
        response = self.client.post(start_url, 
                                  json.dumps({'report_type': 'cfd'}),
                                  content_type='application/json')
        job_id = response.json()['job_id']
        
        # Check status
        check_url = reverse('reports:api_check_report_job', kwargs={'job_id': job_id})
        response = self.client.get(check_url)
        self.assertEqual(response.json()['status'], 'done')
