from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from reports.models import Project, Task

class FileUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.project = Project.objects.create(name='Test Project', code='TP', owner=self.user)
        self.task = Task.objects.create(title='Test Task', project=self.project, user=self.user)
        self.client = Client()
        self.client.login(username='testuser', password='password')

    def test_upload_valid_file_project(self):
        f = SimpleUploadedFile("test.txt", b"content", content_type="text/plain")
        response = self.client.post(
            reverse('projects:project_upload_attachment', args=[self.project.id]),
            {'files': [f]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')

    def test_upload_invalid_extension_project(self):
        f = SimpleUploadedFile("malware.exe", b"content", content_type="application/x-msdownload")
        response = self.client.post(
            reverse('projects:project_upload_attachment', args=[self.project.id]),
            {'files': [f]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('不支持的文件类型', response.json()['message'])

    def test_upload_valid_file_task(self):
        f = SimpleUploadedFile("test.pdf", b"content", content_type="application/pdf")
        response = self.client.post(
            reverse('tasks:task_upload_attachment', args=[self.task.id]),
            {'files': [f]}
        )
        self.assertEqual(response.status_code, 200)

    def test_upload_invalid_extension_task(self):
        f = SimpleUploadedFile("script.py", b"print('hack')", content_type="text/x-python")
        response = self.client.post(
            reverse('tasks:task_upload_attachment', args=[self.task.id]),
            {'files': [f]}
        )
        self.assertEqual(response.status_code, 400)
