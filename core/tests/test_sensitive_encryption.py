from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase

from core.models import Profile, SalaryHistory


class SensitiveFieldEncryptionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('encrypted-user', password='password')

    def test_profile_sensitive_values_are_encrypted_at_rest(self):
        profile = Profile.objects.create(
            user=self.user,
            probation_salary=Decimal('5000.00'),
            official_salary=Decimal('7000.00'),
            intermediary_fee_amount=Decimal('250.00'),
            usdt_address='T-sensitive-wallet-address',
            hr_note='Confidential note',
        )
        profile.refresh_from_db()

        self.assertEqual(profile.probation_salary, Decimal('5000.00'))
        self.assertEqual(profile.usdt_address, 'T-sensitive-wallet-address')
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT probation_salary_secure, usdt_address_secure, hr_note_secure '
                'FROM core_profile WHERE id = %s',
                [profile.id],
            )
            salary, address, note = cursor.fetchone()
        self.assertTrue(salary.startswith('enc:v1:'))
        self.assertTrue(address.startswith('enc:v1:'))
        self.assertTrue(note.startswith('enc:v1:'))
        self.assertNotIn('5000', salary)
        self.assertNotIn('sensitive-wallet', address)

    def test_salary_history_uses_legacy_properties_with_encrypted_storage(self):
        history = SalaryHistory.objects.create(
            user=self.user,
            changed_by=self.user,
            old_official=Decimal('6000.00'),
            new_official=Decimal('7000.00'),
        )
        history.refresh_from_db()

        self.assertEqual(history.old_official, Decimal('6000.00'))
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT old_official_secure FROM core_salaryhistory WHERE id = %s',
                [history.id],
            )
            raw_value = cursor.fetchone()[0]
        self.assertTrue(raw_value.startswith('enc:v1:'))
