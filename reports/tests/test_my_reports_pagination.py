from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from work_logs.models import DailyReport
from projects.models import Project

User = get_user_model()

class MyReportsPaginationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.force_login(self.user)
        self.url = reverse('reports:my_reports')
        
        # Create 25 reports
        today = timezone.now().date()
        for i in range(25):
            DailyReport.objects.create(
                user=self.user,
                date=today - timezone.timedelta(days=i),
                role='dev',
                today_work=f'Work {i}',
                status='submitted'
            )

    def test_pagination_count(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        
        # Check that we have 20 items on the first page
        self.assertEqual(len(response.context['page_obj']), 20)
        
        # Check that we have 2 pages in total
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 2)
