
from django.test import TestCase, Client
from django.contrib.auth.models import User
from projects.models import Project
from tasks.models import Task, TaskAttachment
from core.models import Profile

class TaskAttachmentPermissionTest(TestCase):
    def setUp(self):
        # Users
        self.superuser = User.objects.create_superuser('super', 'super@test.com', 'password')
        self.owner = User.objects.create_user('owner', 'owner@test.com', 'password') # Task Responsible
        self.uploader = User.objects.create_user('uploader', 'uploader@test.com', 'password')
        self.manager = User.objects.create_user('manager', 'manager@test.com', 'password')
        self.other = User.objects.create_user('other', 'other@test.com', 'password')
        
        # Profile for manager
        Profile.objects.create(user=self.manager, position='pm')

        # Project
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.manager)
        
        # Task
        self.task = Task.objects.create(
            title='Test Task',
            project=self.project,
            user=self.owner,
            status='todo'
        )
        
        # Attachments
        # 1. Uploaded by uploader
        self.att_by_uploader = TaskAttachment.objects.create(
            task=self.task,
            user=self.uploader,
            file='test1.txt'
        )
        
        # 2. Uploaded by owner
        self.att_by_owner = TaskAttachment.objects.create(
            task=self.task,
            user=self.owner,
            file='test2.txt'
        )

    def test_delete_permission(self):
        c = Client()
        
        # 1. Superuser should delete any
        c.login(username='super', password='password')
        resp = c.post(f'/tasks/attachments/{self.att_by_uploader.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TaskAttachment.objects.filter(id=self.att_by_uploader.id).exists())
        
        # Reset
        self.att_by_uploader = TaskAttachment.objects.create(task=self.task, user=self.uploader, file='test1.txt')

        # 2. Task Owner (Responsible) should delete any
        c.login(username='owner', password='password')
        resp = c.post(f'/tasks/attachments/{self.att_by_uploader.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        
        # Reset
        self.att_by_uploader = TaskAttachment.objects.create(task=self.task, user=self.uploader, file='test1.txt')

        # 3. Uploader should delete own
        c.login(username='uploader', password='password')
        resp = c.post(f'/tasks/attachments/{self.att_by_uploader.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        
        # 4. Uploader CANNOT delete others (e.g. owner's file)
        resp = c.post(f'/tasks/attachments/{self.att_by_owner.id}/delete/')
        self.assertEqual(resp.status_code, 403)
        
        # 5. Project Manager (who is NOT super/owner/uploader)
        # Requirement: ONLY Superuser, Task Responsible, Uploader.
        # Current code ALLOWS Project Manager. I expect this to FAIL if I strictly follow requirements.
        # But I haven't changed code yet, so it might pass (return 200).
        # I will assert 403 to confirm I need to fix it.
        c.login(username='manager', password='password')
        resp = c.post(f'/tasks/attachments/{self.att_by_owner.id}/delete/')
        
        # If current code allows manager, this will be 200.
        # I want to ensure it becomes 403.
        # For now, let's see what it returns.
        print(f"Manager delete response: {resp.status_code}")

        # 6. Random user
        c.login(username='other', password='password')
        resp = c.post(f'/tasks/attachments/{self.att_by_owner.id}/delete/')
        self.assertEqual(resp.status_code, 403)

