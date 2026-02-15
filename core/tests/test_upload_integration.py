from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse
from core.models import ChunkedUpload, Profile
from projects.models import Project, ProjectAttachment
from tasks.models import Task, TaskAttachment
import json
import os
import shutil

@override_settings(MEDIA_ROOT='/tmp/django_test_media_integ')
class UploadIntegrationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.client.force_login(self.user)
        self.temp_dir = '/tmp/django_test_media_integ'
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
            
        # Create Project and Task
        self.project = Project.objects.create(name="Test Project", code="TP01", owner=self.user)
        self.task = Task.objects.create(title="Test Task", project=self.project, user=self.user)
        Profile.objects.create(user=self.user)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_project_attachment_flow(self):
        # 1. Init
        init_url = reverse('core:upload_init')
        init_data = {'filename': 'test_project_file.txt', 'size': 100, 'type': 'project'}
        resp = self.client.post(init_url, json.dumps(init_data), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        upload_id = resp.json()['upload_id']
        
        # 2. Chunk
        chunk_url = reverse('core:upload_chunk')
        with open(os.path.join(self.temp_dir, 'chunk1'), 'wb') as f:
            f.write(b'x' * 100)
        with open(os.path.join(self.temp_dir, 'chunk1'), 'rb') as f:
            resp = self.client.post(chunk_url, {'upload_id': upload_id, 'chunk_index': 0, 'offset': 0, 'file': f})
        self.assertEqual(resp.status_code, 200)
        
        # 3. Complete (API)
        complete_url = reverse('core:upload_complete')
        resp = self.client.post(complete_url, json.dumps({'upload_id': upload_id}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        
        # 4. Finalize (Project View)
        finalize_url = reverse('projects:project_upload_attachment', args=[self.project.id])
        resp = self.client.post(finalize_url, {'upload_id': upload_id})
        self.assertEqual(resp.status_code, 200)
        
        # Verify
        self.assertTrue(ProjectAttachment.objects.filter(project=self.project).exists())
        attachment = ProjectAttachment.objects.first()
        self.assertEqual(attachment.file_size, 100)

    def test_task_attachment_flow(self):
        # 1. Init
        init_url = reverse('core:upload_init')
        init_data = {'filename': 'test_task_file.jpg', 'size': 200, 'type': 'task'}
        resp = self.client.post(init_url, json.dumps(init_data), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        upload_id = resp.json()['upload_id']
        
        # 2. Chunk
        chunk_url = reverse('core:upload_chunk')
        with open(os.path.join(self.temp_dir, 'chunk1'), 'wb') as f:
            f.write(b'y' * 200)
        with open(os.path.join(self.temp_dir, 'chunk1'), 'rb') as f:
            resp = self.client.post(chunk_url, {'upload_id': upload_id, 'chunk_index': 0, 'offset': 0, 'file': f})
        self.assertEqual(resp.status_code, 200)
        
        # 3. Complete (API)
        complete_url = reverse('core:upload_complete')
        resp = self.client.post(complete_url, json.dumps({'upload_id': upload_id}), content_type='application/json')
        
        # 4. Finalize (Task View)
        finalize_url = reverse('tasks:task_upload_attachment', args=[self.task.id])
        resp = self.client.post(finalize_url, {'upload_id': upload_id})
        self.assertEqual(resp.status_code, 200)
        
        # Verify
        self.assertTrue(TaskAttachment.objects.filter(task=self.task).exists())
        att = TaskAttachment.objects.first()
        self.assertTrue(att.is_image)

    def test_avatar_upload_flow(self):
        # 1. Init
        init_url = reverse('core:upload_init')
        init_data = {'filename': 'avatar.png', 'size': 500, 'type': 'avatar'}
        resp = self.client.post(init_url, json.dumps(init_data), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        upload_id = resp.json()['upload_id']
        
        # 2. Chunk
        chunk_url = reverse('core:upload_chunk')
        with open(os.path.join(self.temp_dir, 'chunk1'), 'wb') as f:
            f.write(b'z' * 500)
        with open(os.path.join(self.temp_dir, 'chunk1'), 'rb') as f:
            resp = self.client.post(chunk_url, {'upload_id': upload_id, 'chunk_index': 0, 'offset': 0, 'file': f})
        
        # 3. Complete (Avatar API)
        # Avatar uses a specific complete endpoint that handles finalization directly
        finalize_url = reverse('core:upload_avatar_complete')
        resp = self.client.post(finalize_url, json.dumps({'upload_id': upload_id}), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('url', resp.json())
        
        # Verify User Preference
        self.user.preferences.refresh_from_db()
        self.assertTrue(self.user.preferences.data['profile']['avatar_data_url'].startswith('/media/avatars/'))

    def test_file_size_limit(self):
        # Project limit is 10MB
        init_url = reverse('core:upload_init')
        init_data = {'filename': 'big.txt', 'size': 11 * 1024 * 1024, 'type': 'project'}
        resp = self.client.post(init_url, json.dumps(init_data), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('exceeds limit', resp.json()['message'])
        
        # Task limit is 50MB (so 11MB is ok)
        init_data['type'] = 'task'
        resp = self.client.post(init_url, json.dumps(init_data), content_type='application/json')
        self.assertEqual(resp.status_code, 200)

    def test_extension_limit(self):
        init_url = reverse('core:upload_init')
        init_data = {'filename': 'script.exe', 'size': 100, 'type': 'default'}
        resp = self.client.post(init_url, json.dumps(init_data), content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Unsupported file type', resp.json()['message'])

    def test_attachment_deletion(self):
        # Create a real file
        from django.core.files.base import ContentFile
        att = ProjectAttachment.objects.create(
            project=self.project,
            uploaded_by=self.user,
            file=ContentFile(b'content', name='to_delete.txt'),
            original_filename='to_delete.txt',
            file_size=7
        )
            
        file_path = att.file.path
        self.assertTrue(os.path.exists(file_path))
        
        # Delete attachment
        att.delete()
        
        # Verify file is gone
        self.assertFalse(os.path.exists(file_path))
