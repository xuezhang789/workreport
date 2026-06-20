from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import SearchIndex
from core.services.search_index import global_search, rebuild_search_index
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport


class SearchIndexingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='password')
        self.outsider = User.objects.create_user('outsider', password='password')
        self.project = Project.objects.create(
            name='Apollo Billing',
            code='APOLLO',
            description='Payment reconciliation platform',
            owner=self.owner,
        )
        self.task = Task.objects.create(
            title='Fix invoice export',
            content='CSV rounding mismatch',
            project=self.project,
            user=self.owner,
        )
        self.report = DailyReport.objects.create(
            user=self.owner,
            date=timezone.localdate(),
            role='dev',
            today_work='Investigated invoice export latency',
        )
        self.report.projects.add(self.project)

    def test_rebuild_search_index_and_permission_filter(self):
        counts = rebuild_search_index()

        self.assertEqual(counts, {'projects': 1, 'tasks': 1, 'reports': 1})
        self.assertEqual(SearchIndex.objects.count(), 3)

        owner_results, _hits = global_search(self.owner, 'invoice', scope='all')
        self.assertEqual([task.id for task in owner_results['tasks']], [self.task.id])
        self.assertEqual([report.id for report in owner_results['reports']], [self.report.id])

        outsider_results, _hits = global_search(self.outsider, 'invoice', scope='all')
        self.assertEqual(outsider_results['projects'], [])
        self.assertEqual(outsider_results['tasks'], [])
        self.assertEqual(outsider_results['reports'], [])

    def test_command_search_falls_back_before_index_rebuild(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('core:command_search_api'), {'q': 'Apollo'})

        self.assertEqual(response.status_code, 200)
        titles = [item['title'] for item in response.json()['results']]
        self.assertIn('Apollo Billing (APOLLO)', titles)
