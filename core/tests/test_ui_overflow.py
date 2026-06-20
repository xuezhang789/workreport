import json
import time
from django.core import mail
from django.test import TestCase, Client
from django.test import override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from core.models import Profile, UserPreference

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
        self.assertIn('class="badge badge-warning email-status-badge" title="未验证 / Unverified"', content)
        self.assertIn('Current email is unverified; keep it and request a code.', content)
        self.assertIn('.email-pending-text strong', content)

    def test_account_settings_supports_legacy_user_without_profile(self):
        legacy_user = get_user_model().objects.create_user(
            username='legacyuser',
            email='legacy@example.com',
            password='password',
        )
        self.client.force_login(legacy_user)

        response = self.client.get(reverse('core:account_settings'))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Profile.objects.filter(user=legacy_user).exists())
        self.assertContains(response, '未验证 / Unverified')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_unverified_current_email_can_request_code(self):
        self.user.email = 'current@example.com'
        self.user.save(update_fields=['email'])
        self.user.profile.email_verified = False
        self.user.profile.save(update_fields=['email_verified'])

        response = self.client.post(
            reverse('core:send_email_code_api'),
            data=json.dumps({'email': 'current@example.com'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(self.client.session['email_verification']['email'], 'current@example.com')
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_verified_current_email_rejects_duplicate_code(self):
        self.user.email = 'current@example.com'
        self.user.save(update_fields=['email'])
        self.user.profile.email_verified = True
        self.user.profile.save(update_fields=['email_verified'])

        response = self.client.post(
            reverse('core:send_email_code_api'),
            data=json.dumps({'email': 'current@example.com'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('already bound and verified', response.json()['error'])

    def test_email_update_marks_profile_verified(self):
        session = self.client.session
        session['email_verification'] = {
            'email': 'verified@example.com',
            'code': '123456',
            'expires_at': time.time() + 300,
        }
        session.save()

        response = self.client.post(reverse('core:account_settings'), {
            'action': 'update_email',
            'email': 'verified@example.com',
            'code': '123456',
        })

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.email, 'verified@example.com')
        self.assertTrue(self.user.profile.email_verified)

    def test_profile_avatar_url_reads_from_preferences(self):
        UserPreference.objects.create(
            user=self.user,
            data={'profile': {'avatar_data_url': '/media/avatars/test.png'}},
        )

        self.assertEqual(self.user.profile.avatar_url, '/media/avatars/test.png')
