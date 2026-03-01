from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from core.models import Profile, Invitation
from projects.models import Project
from tasks.models import Task
from core.constants import TaskStatus
from reports.services.stats import get_performance_stats
from reports.templatetags.safe_md import safe_md
from core.views import register
import json

class OptimizationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='password')
        Profile.objects.create(user=self.user, position='dev')
        
        # Create multiple projects to test N+1
        self.projects = []
        for i in range(5):
            p = Project.objects.create(name=f'Project {i}', code=f'P{i}', owner=self.user, is_active=True)
            self.projects.append(p)
            
            # Create tasks for each project
            for j in range(3):
                Task.objects.create(
                    title=f'Task {i}-{j}',
                    user=self.user,
                    project=p,
                    status=TaskStatus.DONE,
                    due_at=timezone.now() + timezone.timedelta(days=1),
                    completed_at=timezone.now()
                )

    def test_performance_stats_n_plus_1(self):
        """Verify that get_performance_stats does not have N+1 queries when projects increase."""
        # Warm up query cache if any
        get_performance_stats(accessible_projects=Project.objects.all())
        
        with CaptureQueriesContext(connection) as ctx:
            get_performance_stats(accessible_projects=Project.objects.all())
        
        # The number of queries should be constant regardless of project count (5 projects here)
        # It typically involves: 
        # 1. Main aggregation query
        # 2. User/Role/Project grouping queries
        # It should NOT be 5 * N queries.
        # Let's assert it's below a reasonable threshold (e.g., 10 queries for complex stats).
        self.assertLess(len(ctx), 15, f"Too many queries: {len(ctx)}")

    def test_safe_md_xss_protection(self):
        """Verify that safe_md filter correctly escapes XSS payloads."""
        # Test 1: Basic Script Injection
        payload = "<script>alert(1)</script>"
        rendered = safe_md(payload)
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        
        # Test 2: Attribute Injection in Link
        payload = '[Click me](javascript:alert(1))'
        rendered = safe_md(payload)
        # The regex in safe_md only allows http/https, so javascript: should not be linkified or should be safe
        # Currently safe_md regex is: r'\[([^\]]+)\]\((https?://[^"\s<]+)\)'
        # So javascript: won't match and will remain as text (escaped)
        self.assertNotIn('<a href="javascript:', rendered)
        
        # Test 3: Valid Markdown Link
        payload = '[Google](https://google.com)'
        rendered = safe_md(payload)
        self.assertIn('<a href="https://google.com"', rendered)
        self.assertIn('target="_blank"', rendered)

    def test_register_rate_limiting(self):
        """Verify rate limiting on register view."""
        # Use Client to handle sessions automatically
        from django.test import Client
        from django.urls import reverse
        client = Client()
        
        # Create a valid invitation first
        Invitation.objects.create(code='TESTCODE1234', inviter=self.user)
        
        url = reverse('core:register') + '?code=TESTCODE1234'
        
        responses = []
        for _ in range(15):
            # Client automatically handles sessions and middleware
            response = client.get(url)
            responses.append(response.status_code)
            
        # Check if we got any 429s
        self.assertIn(429, responses, "Rate limiting did not trigger 429 response")

