from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Profile
from core.constants import TaskStatus
from projects.models import Project
from tasks.models import Task
from reports.services.stats import get_performance_stats


class PerformanceStatsServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u1', password='pass')
        Profile.objects.create(user=self.user, position='dev')
        self.project = Project.objects.create(name='P1', code='P1', owner=self.user)

        now = timezone.now()
        # Completed task
        t_done = Task.objects.create(
            title='Done Task',
            user=self.user,
            project=self.project,
            status=TaskStatus.DONE,
            due_at=now + timezone.timedelta(days=2),
        )
        t_done.completed_at = now
        t_done.save(update_fields=['completed_at'])

        # Closed task
        t_closed = Task.objects.create(
            title='Closed Task',
            user=self.user,
            project=self.project,
            status=TaskStatus.CLOSED,
            due_at=now + timezone.timedelta(days=1),
        )
        t_closed.completed_at = now
        t_closed.save(update_fields=['completed_at'])

        # Overdue task
        Task.objects.create(
            title='Overdue Task',
            user=self.user,
            project=self.project,
            status=TaskStatus.TODO,
            due_at=now - timezone.timedelta(days=1),
        )

    def test_overall_stats_counts(self):
        stats = get_performance_stats(
            accessible_projects=Project.objects.filter(id=self.project.id)
        )
        self.assertEqual(stats['overall_total'], 3)
        self.assertEqual(stats['overall_overdue'], 1)
        self.assertGreaterEqual(stats['overall_sla_on_time_rate'], 0)
