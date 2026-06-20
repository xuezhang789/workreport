from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from work_logs.models import DailyReport


class DailyReportContentTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='content-user',
            password='test-password',
        )

    def test_legacy_properties_are_stored_in_structured_content(self):
        report = DailyReport.objects.create(
            user=self.user,
            date=date(2026, 6, 19),
            role='dev',
            status='draft',
            today_work='Implemented structured reports',
            progress_issues='None',
            project='Legacy project label',
        )

        report.refresh_from_db()

        self.assertEqual(report.today_work, 'Implemented structured reports')
        self.assertEqual(report.project, 'Legacy project label')
        self.assertEqual(
            report.role_content(),
            {
                'today_work': 'Implemented structured reports',
                'progress_issues': 'None',
                'tomorrow_plan': '',
            },
        )
        self.assertEqual(
            report.content,
            {
                'today_work': 'Implemented structured reports',
                'progress_issues': 'None',
                '_legacy_project': 'Legacy project label',
            },
        )

    def test_empty_legacy_property_removes_json_key(self):
        report = DailyReport.objects.create(
            user=self.user,
            date=date(2026, 6, 20),
            role='qa',
            status='draft',
            testing_scope='Checkout flow',
        )

        report.testing_scope = ''
        report.save(update_fields=['content'])
        report.refresh_from_db()

        self.assertEqual(report.testing_scope, '')
        self.assertNotIn('testing_scope', report.content)

    def test_structured_content_search_covers_all_roles(self):
        report = DailyReport.objects.create(
            user=self.user,
            date=date(2026, 6, 21),
            role='ops',
            status='draft',
            ops_monitoring='Database latency stabilized',
        )

        matches = DailyReport.objects.filter(
            DailyReport.content_search_query('latency')
        )

        self.assertEqual(list(matches), [report])

    def test_content_schema_v2_normalizes_known_and_extension_fields(self):
        report = DailyReport.objects.create(
            user=self.user,
            date=date(2026, 6, 22),
            role='dev',
            status='draft',
            content={
                'today_work': '  shipped schema contract  ',
                'tomorrow_plan': '',
                'custom_metric': {'count': 3},
            },
        )

        report.refresh_from_db()

        self.assertEqual(report.content_schema_version, DailyReport.CURRENT_CONTENT_SCHEMA_VERSION)
        self.assertEqual(report.content['today_work'], 'shipped schema contract')
        self.assertNotIn('tomorrow_plan', report.content)
        self.assertEqual(report.content['_extra'], {'custom_metric': {'count': 3}})

    def test_submitted_report_requires_role_content_when_validated(self):
        report = DailyReport(
            user=self.user,
            date=date(2026, 6, 23),
            role='qa',
            status='submitted',
            content={},
        )

        with self.assertRaises(ValidationError):
            report.full_clean()


class DailyReportContentMigrationTests(TransactionTestCase):
    migrate_from = ('work_logs', '0003_alter_reminderrule_project')
    migrate_to = ('work_logs', '0004_remove_dailyreport_bug_summary_and_more')

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        User = old_apps.get_model('auth', 'User')
        DailyReport = old_apps.get_model('work_logs', 'DailyReport')
        user = User.objects.create(username='migration-user')
        DailyReport.objects.create(
            user_id=user.id,
            date=date(2026, 6, 18),
            role='qa',
            status='draft',
            testing_scope='Regression suite',
            bug_summary='Two defects',
            project='Legacy Alpha',
        )

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        self.apps = self.executor.loader.project_state([self.migrate_to]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_migration_preserves_values_in_both_directions(self):
        DailyReport = self.apps.get_model('work_logs', 'DailyReport')

        report = DailyReport.objects.get(user__username='migration-user')

        self.assertEqual(report.content['testing_scope'], 'Regression suite')
        self.assertEqual(report.content['bug_summary'], 'Two defects')
        self.assertEqual(report.content['_legacy_project'], 'Legacy Alpha')

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        LegacyDailyReport = old_apps.get_model('work_logs', 'DailyReport')
        restored = LegacyDailyReport.objects.get(user__username='migration-user')

        self.assertEqual(restored.testing_scope, 'Regression suite')
        self.assertEqual(restored.bug_summary, 'Two defects')
        self.assertEqual(restored.project, 'Legacy Alpha')
