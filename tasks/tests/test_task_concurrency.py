from django.contrib.auth.models import User
from django.test import TestCase

from core.constants import TaskCategory, TaskStatus
from projects.models import Project
from tasks.models import Task
from tasks.services.state import TaskConflictError, TaskStateService, TaskTransitionError


class TaskConcurrencyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='task-version-user', password='password')
        self.project = Project.objects.create(name='Task Version Project', code='TVP', owner=self.user)

    def test_status_transition_increments_version_and_sets_completion_time(self):
        task = Task.objects.create(
            title='Versioned task',
            project=self.project,
            user=self.user,
            category=TaskCategory.TASK,
            status=TaskStatus.TODO,
        )

        updated, old_status = TaskStateService.transition_task_status(
            task.id,
            TaskStatus.DONE,
            expected_version=task.version,
        )

        self.assertEqual(old_status, TaskStatus.TODO)
        self.assertEqual(updated.status, TaskStatus.DONE)
        self.assertEqual(updated.version, 2)
        self.assertIsNotNone(updated.completed_at)

    def test_stale_expected_version_raises_conflict_without_update(self):
        task = Task.objects.create(
            title='Conflict task',
            project=self.project,
            user=self.user,
            category=TaskCategory.TASK,
            status=TaskStatus.TODO,
        )

        with self.assertRaises(TaskConflictError):
            TaskStateService.transition_task_status(
                task.id,
                TaskStatus.DONE,
                expected_version=task.version + 1,
            )

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertEqual(task.version, 1)
        self.assertIsNone(task.completed_at)

    def test_invalid_bug_transition_raises_transition_error(self):
        task = Task.objects.create(
            title='Bug flow conflict',
            project=self.project,
            user=self.user,
            category=TaskCategory.BUG,
            status=TaskStatus.NEW,
        )

        with self.assertRaises(TaskTransitionError):
            TaskStateService.transition_task_status(
                task.id,
                TaskStatus.CLOSED,
                expected_version=task.version,
            )

        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.NEW)
        self.assertEqual(task.version, 1)
