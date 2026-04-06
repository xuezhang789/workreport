from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from reports.models import DailyReport
from django.utils import timezone

User = get_user_model()

class MyReportsPaginationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client.login(username='testuser', password='password')
        
        # Create 25 reports
        for i in range(25):
            DailyReport.objects.create(
                user=self.user,
                date=timezone.now().date() - timezone.timedelta(days=i),
                today_work=f"Report {i}",
                status='submitted'
            )

    def test_default_pagination(self):
        """Test default per_page is 20"""
        response = self.client.get(reverse('reports:my_reports'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 20)
        self.assertEqual(response.context['per_page'], 20)
        self.assertTrue(response.context['page_obj'].has_next())

    def test_custom_per_page_10(self):
        """Test per_page=10"""
        response = self.client.get(reverse('reports:my_reports'), {'per_page': 10})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 10)
        self.assertEqual(response.context['per_page'], 10)
        self.assertEqual(response.context['page_obj'].paginator.num_pages, 3) # 25/10 = 2.5 -> 3

    def test_custom_per_page_50(self):
        """Test per_page=50 (should show all 25)"""
        response = self.client.get(reverse('reports:my_reports'), {'per_page': 50})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 25)
        self.assertEqual(response.context['per_page'], 50)
        self.assertFalse(response.context['page_obj'].has_next())

    def test_invalid_per_page_fallback(self):
        """Test invalid per_page falls back to 20"""
        response = self.client.get(reverse('reports:my_reports'), {'per_page': 999})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 20)
        self.assertEqual(response.context['per_page'], 20)

    def test_page_navigation(self):
        """Test navigating to page 2"""
        response = self.client.get(reverse('reports:my_reports'), {'page': 2, 'per_page': 10})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 10) # 11-20
        self.assertEqual(response.context['page_obj'].number, 2)

    def test_mobile_and_card_interaction_markup(self):
        """My reports page should render accessible mobile filter and clickable cards."""
        response = self.client.get(reverse('reports:my_reports'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="mobileFilterToggle"')
        self.assertContains(response, 'aria-controls="filterSection"')
        self.assertContains(response, 'data-report-url=')
        self.assertContains(response, 'id="perPageSelect"')
        self.assertContains(response, 'id="jumpPageBtn"')
