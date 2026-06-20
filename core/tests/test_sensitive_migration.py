from datetime import date
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SensitiveFieldMigrationTests(TransactionTestCase):
    migrate_from = ('core', '0010_alter_notification_notification_type')
    migrate_to = ('core', '0011_remove_profile_hr_note_and_more')

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        User = old_apps.get_model('auth', 'User')
        Profile = old_apps.get_model('core', 'Profile')
        SalaryHistory = old_apps.get_model('core', 'SalaryHistory')
        user = User.objects.create(username='sensitive-migration-user')
        changer = User.objects.create(username='sensitive-migration-admin')
        Profile.objects.create(
            user_id=user.id,
            probation_salary=Decimal('5000.00'),
            official_salary=Decimal('7000.00'),
            intermediary_fee_amount=Decimal('100.00'),
            usdt_address='legacy-wallet',
            hr_note='legacy-note',
            hire_date=date(2025, 1, 1),
        )
        SalaryHistory.objects.create(
            user_id=user.id,
            changed_by_id=changer.id,
            old_official=Decimal('6000.00'),
            new_official=Decimal('7000.00'),
        )

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        self.apps = executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_values_are_encrypted_and_reversibly_migrated(self):
        Profile = self.apps.get_model('core', 'Profile')
        profile = Profile.objects.get(user__username='sensitive-migration-user')
        self.assertEqual(profile.official_salary_secure, Decimal('7000.00'))
        self.assertEqual(profile.usdt_address_secure, 'legacy-wallet')

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT official_salary_secure, usdt_address_secure FROM core_profile WHERE id = %s',
                [profile.id],
            )
            salary_raw, address_raw = cursor.fetchone()
        self.assertTrue(salary_raw.startswith('enc:v1:'))
        self.assertTrue(address_raw.startswith('enc:v1:'))

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        LegacyProfile = old_apps.get_model('core', 'Profile')
        restored = LegacyProfile.objects.get(user__username='sensitive-migration-user')
        self.assertEqual(restored.official_salary, Decimal('7000.00'))
        self.assertEqual(restored.usdt_address, 'legacy-wallet')
        self.assertEqual(restored.hr_note, 'legacy-note')
