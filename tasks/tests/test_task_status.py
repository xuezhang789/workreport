from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from projects.models import Project
from tasks.models import Task, TaskSlaTimer
from core.constants import TaskStatus
from tasks.services.sla import calculate_sla_info

class TaskStatusFlowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.user)

    def test_default_status(self):
        task = Task.objects.create(
            title='New Task',
            project=self.project,
            user=self.user
        )
        self.assertEqual(task.status, TaskStatus.TODO)
        self.assertEqual(task.get_status_display(), '待处理 / To Do')

    def test_status_transition(self):
        task = Task.objects.create(
            title='Flow Task',
            project=self.project,
            user=self.user,
            status=TaskStatus.TODO
        )
        
        # Move to In Progress
        task.status = TaskStatus.IN_PROGRESS
        task.save()
        self.assertEqual(Task.objects.filter(status=TaskStatus.IN_PROGRESS).count(), 1)
        
        # Move to Done
        task.status = TaskStatus.DONE
        task.completed_at = timezone.now()
        task.save()
        self.assertEqual(Task.objects.filter(status=TaskStatus.DONE).count(), 1)

class SLACalculationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('slauser', 'sla@example.com', 'password')
        # Project with 24h SLA
        self.project = Project.objects.create(
            name='SLA Project', 
            code='SLA', 
            owner=self.user,
            sla_hours=24
        )
        
    def test_basic_sla_calculation(self):
        now = timezone.now()
        task = Task.objects.create(
            title='SLA Task',
            project=self.project,
            user=self.user,
            created_at=now
        )
        # Manually set created_at because auto_now_add is immutable in some contexts, 
        # but here we rely on creation time.
        # Actually calculate_sla_info uses created_at.
        
        info = calculate_sla_info(task, as_of=now)
        # Expected remaining: approx 24 hours
        self.assertTrue(23.9 <= info['remaining_hours'] <= 24.1)
        self.assertEqual(info['status'], 'normal')
        
    def test_sla_pause_logic(self):
        now = timezone.now()
        task = Task.objects.create(
            title='Paused Task',
            project=self.project,
            user=self.user
        )
        
        # Start timer
        timer = TaskSlaTimer.objects.create(task=task)
        
        # Pause for 2 hours
        timer.paused_at = now - timedelta(hours=2)
        timer.save()
        
        # Check SLA
        # As of now, it has been paused for 2 hours.
        # So effective due date should be pushed back by 2 hours.
        # Original deadline: created_at + 24h
        # New deadline: created_at + 26h
        # Remaining time from now: (created_at + 26h) - now
        # Since created_at approx now, remaining should be approx 26h
        
        info = calculate_sla_info(task, as_of=now)
        self.assertTrue(25.9 <= info['remaining_hours'] <= 26.1)
        self.assertTrue(info['is_paused'])

    def test_sla_completion_on_time(self):
        now = timezone.now()
        created_at = now - timedelta(hours=10)
        
        task = Task.objects.create(
            title='Done Task',
            project=self.project,
            user=self.user
        )
        task.created_at = created_at
        task.save()
        
        # Complete it now (10 hours after creation, within 24h SLA)
        task.status = TaskStatus.DONE
        task.completed_at = now
        task.save()
        
        info = calculate_sla_info(task, as_of=now)
        self.assertEqual(info['status'], 'on_time')
        self.assertEqual(info['level'], 'success')

    def test_sla_completion_overdue(self):
        now = timezone.now()
        created_at = now - timedelta(hours=30) # Created 30h ago
        
        task = Task.objects.create(
            title='Overdue Task',
            project=self.project,
            user=self.user
        )
        task.created_at = created_at
        task.save()
        
        # Complete it now (30h > 24h SLA)
        task.status = TaskStatus.DONE
        task.completed_at = now
        task.save()
        
        info = calculate_sla_info(task, as_of=now)
        self.assertEqual(info['status'], 'overdue')
        self.assertEqual(info['level'], 'red')
