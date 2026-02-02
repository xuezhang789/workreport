from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import Profile
from core.constants import TaskStatus
from projects.models import Project
from tasks.models import Task
from reports.services.stats import get_performance_stats


class PerformanceStatsQueryBudgetTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u2', password='pass')
        Profile.objects.create(user=self.user, position='dev')
        self.project = Project.objects.create(name='P2', code='P2', owner=self.user)

        now = timezone.now()
        for i in range(5):
            task = Task.objects.create(
                title=f'Task {i}',
                user=self.user,
                project=self.project,
                status=TaskStatus.DONE if i % 2 == 0 else TaskStatus.TODO,
                due_at=now + timezone.timedelta(days=1),
            )
            if task.status == TaskStatus.DONE:
                task.completed_at = now
                task.save(update_fields=['completed_at'])

    def test_query_budget(self):
        with CaptureQueriesContext(connection) as ctx:
            get_performance_stats(
                accessible_projects=Project.objects.filter(id=self.project.id)
            )
        self.assertLessEqual(len(ctx), 6)
