
from django.test import TestCase, Client
from django.contrib.auth.models import User
from projects.models import Project, ProjectAttachment
from core.models import Profile

class ProjectAttachmentPermissionTest(TestCase):
    def setUp(self):
        # Users
        self.superuser = User.objects.create_superuser('super', 'super@test.com', 'password')
        self.owner = User.objects.create_user('owner', 'owner@test.com', 'password') # Project Owner
        self.uploader = User.objects.create_user('uploader', 'uploader@test.com', 'password')
        self.manager = User.objects.create_user('manager', 'manager@test.com', 'password')
        self.other = User.objects.create_user('other', 'other@test.com', 'password')
        
        # Profile for manager (to be added as manager)
        Profile.objects.create(user=self.manager, position='pm')

        # Project
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.owner)
        self.project.managers.add(self.manager)
        
        # Attachments
        # 1. Uploaded by uploader
        self.att_by_uploader = ProjectAttachment.objects.create(
            project=self.project,
            uploaded_by=self.uploader,
            file='test1.txt',
            original_filename='test1.txt'
        )
        
        # 2. Uploaded by owner
        self.att_by_owner = ProjectAttachment.objects.create(
            project=self.project,
            uploaded_by=self.owner,
            file='test2.txt',
            original_filename='test2.txt'
        )

    def test_delete_permission(self):
        c = Client()
        
        # 1. Superuser should delete any
        c.login(username='super', password='password')
        resp = c.post(f'/projects/attachments/{self.att_by_uploader.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ProjectAttachment.objects.filter(id=self.att_by_uploader.id).exists())
        
        # Reset
        self.att_by_uploader = ProjectAttachment.objects.create(project=self.project, uploaded_by=self.uploader, file='test1.txt')

        # 2. Project Owner should delete any
        c.login(username='owner', password='password')
        resp = c.post(f'/projects/attachments/{self.att_by_uploader.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        
        # Reset
        self.att_by_uploader = ProjectAttachment.objects.create(project=self.project, uploaded_by=self.uploader, file='test1.txt')

        # 3. Uploader should delete own
        c.login(username='uploader', password='password')
        resp = c.post(f'/projects/attachments/{self.att_by_uploader.id}/delete/')
        self.assertEqual(resp.status_code, 200)
        
        # 4. Uploader CANNOT delete others (e.g. owner's file)
        resp = c.post(f'/projects/attachments/{self.att_by_owner.id}/delete/')
        self.assertEqual(resp.status_code, 403)
        
        # 5. Project Manager (who is NOT super/owner/uploader)
        # Requirement: Should NOT delete.
        c.login(username='manager', password='password')
        resp = c.post(f'/projects/attachments/{self.att_by_owner.id}/delete/')
        self.assertEqual(resp.status_code, 403)

        # 6. Random user
        c.login(username='other', password='password')
        resp = c.post(f'/projects/attachments/{self.att_by_owner.id}/delete/')
        self.assertEqual(resp.status_code, 403)
