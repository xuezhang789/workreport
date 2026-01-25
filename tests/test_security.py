from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from reports.templatetags.reports_filters import mask_email

class SecurityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='user', password='password')
        self.admin = User.objects.create_user(username='admin', password='password', is_staff=True)
        self.client = Client()

    def test_username_check_api_permissions(self):
        # Normal user -> 403
        self.client.login(username='user', password='password')
        response = self.client.get(reverse('reports:username_check_api'), {'username': 'test'})
        self.assertEqual(response.status_code, 403)

        # Admin -> 200
        self.client.login(username='admin', password='password')
        response = self.client.get(reverse('reports:username_check_api'), {'username': 'test'})
        self.assertEqual(response.status_code, 200)

    def test_mask_email_filter(self):
        self.assertEqual(mask_email('arlo@example.com'), 'a***o@example.com')
        self.assertEqual(mask_email('me@test.com'), 'm***@test.com') # len 2
        self.assertEqual(mask_email('a@b.com'), 'a***@b.com') # len 1
        self.assertEqual(mask_email('invalid'), 'invalid')
        self.assertEqual(mask_email(None), None)
