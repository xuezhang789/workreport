
from django.test import TestCase, override_settings
from django.core.files.base import ContentFile
from tasks.models import Task, TaskAttachment
from projects.models import Project, ProjectAttachment
from django.contrib.auth.models import User
import os
import shutil
from django.conf import settings

class AttachmentLifecycleTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.user)
        self.task = Task.objects.create(title='Test Task', project=self.project, user=self.user)
        
        # Create a temp media root for this test
        self.test_media_root = os.path.join(settings.BASE_DIR, 'test_lifecycle_media')
        if not os.path.exists(self.test_media_root):
            os.makedirs(self.test_media_root)

        # Clear RouterStorage handlers cache to ensure new settings are used
        TaskAttachment._meta.get_field('file').storage._handlers = {}
        ProjectAttachment._meta.get_field('file').storage._handlers = {}

    def tearDown(self):
        if os.path.exists(self.test_media_root):
            shutil.rmtree(self.test_media_root)

    def test_task_file_deletion(self):
        with override_settings(MEDIA_ROOT=self.test_media_root):
            content = b'task file content'
            attachment = TaskAttachment.objects.create(
                task=self.task,
                user=self.user,
                file=ContentFile(content, name='task_delete.txt')
            )
            
            # Django's file.path might be absolute.
            # RouterStorage default local handler uses os.path.join(location, name)
            # location defaults to MEDIA_ROOT/local
            
            file_path = attachment.file.path
            self.assertTrue(os.path.exists(file_path))
            
            # Delete attachment
            attachment.delete()
            
            # Verify file is gone
            self.assertFalse(os.path.exists(file_path))

    def test_project_file_deletion(self):
        with override_settings(MEDIA_ROOT=self.test_media_root):
            content = b'project file content'
            attachment = ProjectAttachment.objects.create(
                project=self.project,
                uploaded_by=self.user,
                file=ContentFile(content, name='project_delete.txt'),
                original_filename='project_delete.txt'
            )
            
            file_path = attachment.file.path
            self.assertTrue(os.path.exists(file_path))
            
            attachment.delete()
            self.assertFalse(os.path.exists(file_path))

    def test_duplicate_filename_model(self):
        with override_settings(MEDIA_ROOT=self.test_media_root):
            content = b'content 1'
            att1 = TaskAttachment.objects.create(
                task=self.task,
                user=self.user,
                file=ContentFile(content, name='dup_model.txt')
            )
            
            content2 = b'content 2'
            att2 = TaskAttachment.objects.create(
                task=self.task,
                user=self.user,
                file=ContentFile(content2, name='dup_model.txt')
            )
            
            path1 = att1.file.path
            path2 = att2.file.path
            
            self.assertNotEqual(att1.file.name, att2.file.name)
            self.assertTrue(os.path.exists(path1))
            self.assertTrue(os.path.exists(path2))
            
            att1.delete()
            att2.delete()
            self.assertFalse(os.path.exists(path1))
            self.assertFalse(os.path.exists(path2))
