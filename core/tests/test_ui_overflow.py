from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from core.models import Profile

class PersonalCenterUITest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(username='testuser', password='password')
        # Ensure profile exists
        if not hasattr(self.user, 'profile'):
            Profile.objects.create(user=self.user)
        # Note: email_verified field might be missing in model, effectively False/None
        self.client.force_login(self.user)

    def test_overview_badge_overflow_protection(self):
        """
        Test that the unverified badge has overflow protection classes and attributes.
        """
        url = reverse('core:account_settings')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Check for badge container
        self.assertIn('class="badge-container"', content)

        # Check for unverified badge with title attribute (Tooltip)
        # We expect "Unverified" state by default
        expected_title = 'title="未验证 / Unverified"'
        self.assertIn(expected_title, content)

        # Check for CSS definitions (Presence of new styles)
        self.assertIn('.badge-container {', content)
        self.assertIn('text-overflow: ellipsis;', content)
        self.assertIn('max-width: 100%;', content)
        
        # Check responsive media query presence
        self.assertIn('@media (max-width: 375px)', content)
        self.assertIn('max-width: 140px;', content)
