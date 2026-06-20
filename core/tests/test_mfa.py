from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from core.models import MFARecoveryCode


@override_settings(MFA_REQUIRED_FOR_SUPERUSERS=True)
class SuperuserMFATests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('mfa-admin', 'admin@example.com', 'password')
        self.client.force_login(self.admin)

    def test_privileged_page_redirects_to_setup_without_device(self):
        response = self.client.get(reverse('reports:personnel_list'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('core:mfa_setup'), response.url)

    def test_setup_confirms_device_and_creates_recovery_codes(self):
        response = self.client.get(reverse('core:mfa_setup'))
        self.assertEqual(response.status_code, 200)
        device = TOTPDevice.objects.get(user=self.admin)
        token = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift).token()

        response = self.client.post(reverse('core:mfa_setup'), {'token': str(token)})

        self.assertEqual(response.status_code, 200)
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.admin, used_at__isnull=True).count(), 10)

    def test_recovery_code_is_single_use(self):
        device = TOTPDevice.objects.create(user=self.admin, name='primary', confirmed=True)
        MFARecoveryCode.replace_for_user(self.admin, ['RECOVERY01'])

        first = self.client.post(reverse('core:mfa_verify'), {'token': 'RECOVERY01', 'next': '/'})
        self.assertEqual(first.status_code, 302)
        self.client.logout()
        self.client.force_login(self.admin)
        second = self.client.post(reverse('core:mfa_verify'), {'token': 'RECOVERY01', 'next': '/'})

        self.assertEqual(second.status_code, 200)
        self.assertContains(second, '验证码或恢复码无效')
