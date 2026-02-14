from django.test import TestCase, Client
from django.contrib.auth.models import User
from core.models import Profile
from django.urls import reverse
import json
from datetime import date, timedelta

class HRApiTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.user = User.objects.create_user('user', 'user@example.com', 'password')
        Profile.objects.create(user=self.user, position='dev')
        self.client = Client()

    def test_hr_info_update_admin(self):
        self.client.force_login(self.admin)
        url = reverse('reports:api_hr_info_update', args=[self.user.id])
        data = {
            'employment_status': 'active',
            'hire_date': '2023-01-01',
            'probation_months': 3,
            'probation_salary': 5000,
            'official_salary': 6000,
            'salary_currency': 'USDT',
            'resignation_date': '',
            'hr_note': 'Test note'
        }
        response = self.client.put(url, json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.probation_salary, 5000)
        self.assertEqual(self.user.profile.official_salary, 6000)
        self.assertEqual(self.user.profile.salary_currency, 'USDT')
        self.assertEqual(self.user.profile.hire_date, date(2023, 1, 1))

    def test_hr_info_update_permission(self):
        self.client.force_login(self.user)
        url = reverse('reports:api_hr_info_update', args=[self.user.id])
        response = self.client.put(url, {}, content_type='application/json')
        # user_passes_test usually redirects to login if failed, or 403 if raise_exception=True? 
        # Default behavior of user_passes_test is redirect to login_url.
        # Check if it redirects or 302.
        self.assertEqual(response.status_code, 302) 

    def test_validation_logic(self):
        self.client.force_login(self.admin)
        url = reverse('reports:api_hr_info_update', args=[self.user.id])
        
        # 1. Invalid probation months
        data = {'probation_months': 12}
        response = self.client.put(url, json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('probation_months', response.json()['errors'])

        # 2. Official < Probation salary
        data = {'probation_salary': 6000, 'official_salary': 5000}
        response = self.client.put(url, json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('official_salary', response.json()['errors'])

        # 3. Future hire date
        future = (date.today() + timedelta(days=10)).strftime('%Y-%m-%d')
        data = {'hire_date': future}
        response = self.client.put(url, json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('hire_date', response.json()['errors'])

        # 4. Invalid currency
        data = {'salary_currency': 'EUR'}
        response = self.client.put(url, json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('salary_currency', response.json()['errors'])
