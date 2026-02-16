from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class AuthPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='existinguser', password='password123')

    def test_login_page_renders(self):
        response = self.client.get(reverse('core:login'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/core/login/"')  # Check if action attribute is present

    def test_register_page_renders(self):
        url = reverse('core:register')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/core/register/"') # Check action attribute

    def test_username_check_api_public(self):
        import time
        # Test existing username
        response = self.client.get(reverse('core:username_check_api'), {'username': 'existinguser'})
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'available': False, 'reason': '用户名已存在 / Username already taken'})

        time.sleep(1.0) # Wait for throttle
        # Test new username
        response = self.client.get(reverse('core:username_check_api'), {'username': 'newuser'})
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'available': True})

    def test_username_check_api_empty(self):
        response = self.client.get(reverse('core:username_check_api'))
        self.assertEqual(response.status_code, 400)
