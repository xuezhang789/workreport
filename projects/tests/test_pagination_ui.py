from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from projects.models import Project
from django.utils import timezone
import datetime

class ProjectPaginationUITest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.client = Client()
        self.client.force_login(self.user)
        
        # Create 25 projects
        for i in range(25):
            Project.objects.create(
                name=f"Project {i}",
                code=f"P{i}",
                owner=self.user,
                is_active=True,
                created_at=timezone.now() - datetime.timedelta(days=i)
            )

    def test_pagination_ui_elements(self):
        """Test that the pagination toolbar structure is present."""
        response = self.client.get(reverse('projects:project_list'), {'per_page': 10})
        self.assertEqual(response.status_code, 200)
        
        self.assertContains(response, 'class="pagination-toolbar"')
        self.assertContains(response, 'class="left-info"')
        self.assertEqual(response.context['page_obj'].paginator.count, 25)
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 3)

        self.assertContains(response, 'class="center-controls"')
        self.assertContains(response, 'disabled')
        self.assertContains(response, 'hx-get="/projects/?page=2')

        self.assertContains(response, 'class="right-actions"')
        self.assertContains(response, 'data-project-per-page')
        self.assertContains(response, 'data-jump-page-trigger')
        self.assertContains(response, 'id="jump-page-input"')
        
    def test_pagination_htmx_attributes(self):
        """Test that pagination controls have HTMX attributes."""
        response = self.client.get(reverse('projects:project_list'), {'per_page': 10})
        
        # Check Next button has hx-get, hx-target, hx-push-url
        self.assertContains(response, 'hx-target="#projectListContainer"')
        self.assertContains(response, 'hx-push-url="true"')
        self.assertContains(response, 'hx-indicator="#loadingOverlay"')

    def test_jump_to_page_input(self):
        """Test the jump input max attribute matches total pages."""
        response = self.client.get(reverse('projects:project_list'), {'per_page': 10})
        # Should have max="3"
        self.assertContains(response, 'max="3"')
