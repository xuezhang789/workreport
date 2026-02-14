from django.test import TestCase, Client
from django.contrib.auth.models import User
from core.models import Profile
from django.urls import reverse
import json

class IntermediaryFieldTest(TestCase):
    def setUp(self):
        # Create a superuser
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.client = Client()
        self.client.force_login(self.admin)
        
        # Create a test user
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.profile = Profile.objects.create(user=self.user)
        
        self.url = reverse('reports:api_hr_info_update', args=[self.user.id])

    def test_intermediary_valid_update(self):
        """Test valid update with both company and fee"""
        data = {
            "employment_status": "active",
            "intermediary_company": "Test Company",
            "intermediary_fee_amount": "1000.00",
            "intermediary_fee_currency": "CNY"
        }
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        if response.status_code != 200:
            print(f"Update Failed: {response.json()}")
        self.assertEqual(response.status_code, 200)
        
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.intermediary_company, "Test Company")
        self.assertEqual(float(self.profile.intermediary_fee_amount), 1000.00)
        self.assertEqual(self.profile.intermediary_fee_currency, "CNY")

    def test_intermediary_valid_empty(self):
        """Test valid update with neither company nor fee"""
        data = {
            "employment_status": "active",
            "intermediary_company": "",
            "intermediary_fee_amount": "",
            "intermediary_fee_currency": "CNY"
        }
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        if response.status_code != 200:
            print(f"Empty Update Failed: {response.json()}")
        self.assertEqual(response.status_code, 200)
        
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.intermediary_company)
        self.assertIsNone(self.profile.intermediary_fee_amount)

    def test_intermediary_invalid_company_only(self):
        """Test invalid: Company set but no fee"""
        data = {
            "employment_status": "active",
            "intermediary_company": "Test Company",
            "intermediary_fee_amount": "",
            "intermediary_fee_currency": "CNY"
        }
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("intermediary_fee_amount", response.json()['errors'])

    def test_intermediary_invalid_fee_only(self):
        """Test invalid: Fee set but no company"""
        data = {
            "employment_status": "active",
            "intermediary_company": "",
            "intermediary_fee_amount": "500.00",
            "intermediary_fee_currency": "CNY"
        }
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("intermediary_company", response.json()['errors'])

    def test_intermediary_currency_validation(self):
        """Test invalid currency"""
        data = {
            "employment_status": "active",
            "intermediary_company": "Test Company",
            "intermediary_fee_amount": "100.00",
            "intermediary_fee_currency": "EUR" # Invalid
        }
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("intermediary_fee_currency", response.json()['errors'])

    def test_intermediary_fee_validation(self):
        """Test negative fee"""
        data = {
            "employment_status": "active",
            "intermediary_company": "Test Company",
            "intermediary_fee_amount": "-100.00",
            "intermediary_fee_currency": "CNY"
        }
        response = self.client.put(self.url, json.dumps(data), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("intermediary_fee_amount", response.json()['errors'])
