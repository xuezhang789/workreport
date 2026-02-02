from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from work_logs.models import DailyReport
from projects.models import Project

User = get_user_model()

class AdminReportsPaginationTest(TestCase):
    def setUp(self):
        self.client = Client()
        # Admin reports usually requires superuser or management permission
        self.admin = User.objects.create_superuser(username='admin', password='password')
        self.client.force_login(self.admin)
        self.url = reverse('reports:admin_reports')
        
        # Create 30 reports (enough to span 2 pages if limit is 28)
        today = timezone.now().date()
        for i in range(30):
            DailyReport.objects.create(
                user=self.admin,
                date=today - timezone.timedelta(days=i),
                role='dev',
                today_work=f'Work {i}',
                status='submitted'
            )

    def test_pagination_count(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        
        # Check that we have 28 items on the first page
        self.assertEqual(len(response.context['page_obj']), 28)
        
        # Check that we have 2 pages in total (30 items total, 28 per page -> 1 full page + 2 items)
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 2)
