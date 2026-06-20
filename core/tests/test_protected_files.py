import shutil

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Contract, Profile
from projects.models import Project, ProjectAttachment
from tasks.models import Task, TaskAttachment


@override_settings(MEDIA_ROOT='/tmp/django_test_protected_files')
class ProtectedFileTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='password')
        self.outsider = User.objects.create_user('outsider', password='password')
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.project = Project.objects.create(name='Private Project', code='PRIVATE', owner=self.owner)
        self.project_attachment = ProjectAttachment.objects.create(
            project=self.project,
            uploaded_by=self.owner,
            file=ContentFile(b'project secret', name='project.txt'),
            original_filename='project secret.txt',
            file_size=14,
        )
        self.task = Task.objects.create(title='Private Task', project=self.project, user=self.owner)
        self.task_attachment = TaskAttachment.objects.create(
            task=self.task,
            user=self.owner,
            file=ContentFile(b'task secret', name='task.txt'),
        )
        self.contract = Contract.objects.create(
            user=self.owner,
            uploaded_by=self.admin,
            file=ContentFile(b'contract secret', name='contract.txt'),
            original_filename='employment contract.txt',
        )
        self.profile = Profile.objects.create(user=self.owner)
        self.profile.usdt_qr_code.save(
            'payment.png',
            ContentFile(b'\x89PNG\r\n\x1a\nimage'),
            save=True,
        )

    def tearDown(self):
        shutil.rmtree('/tmp/django_test_protected_files', ignore_errors=True)

    def _body(self, response):
        return b''.join(response.streaming_content)

    def test_project_and_task_files_require_project_access(self):
        self.client.force_login(self.owner)
        project_response = self.client.get(
            reverse('projects:project_attachment_file', args=[self.project_attachment.id]),
        )
        task_response = self.client.get(
            reverse('tasks:task_attachment_file', args=[self.task_attachment.id]),
        )

        self.assertEqual(project_response.status_code, 200)
        self.assertEqual(self._body(project_response), b'project secret')
        self.assertEqual(task_response.status_code, 200)
        self.assertEqual(self._body(task_response), b'task secret')
        self.assertEqual(project_response['Cache-Control'], 'private, no-store')
        self.assertEqual(project_response['X-Content-Type-Options'], 'nosniff')

        self.client.force_login(self.outsider)
        self.assertEqual(
            self.client.get(reverse('projects:project_attachment_file', args=[self.project_attachment.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse('tasks:task_attachment_file', args=[self.task_attachment.id])).status_code,
            404,
        )

    def test_contract_and_payment_qr_are_admin_only(self):
        contract_url = reverse('reports:api_contract_file', args=[self.contract.id]) + '?download=1'
        payment_url = reverse('reports:api_payment_qr_file', args=[self.owner.id])

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(contract_url).status_code, 302)
        self.assertEqual(self.client.get(payment_url).status_code, 302)

        self.client.force_login(self.admin)
        contract_response = self.client.get(contract_url)
        payment_response = self.client.get(payment_url)
        self.assertEqual(contract_response.status_code, 200)
        self.assertIn('attachment;', contract_response['Content-Disposition'])
        self.assertEqual(self._body(contract_response), b'contract secret')
        self.assertEqual(payment_response.status_code, 200)
        self.assertEqual(self._body(payment_response), b'\x89PNG\r\n\x1a\nimage')

    def test_direct_private_media_url_is_not_registered(self):
        response = self.client.get(f'/media/{self.project_attachment.file.name}')
        self.assertEqual(response.status_code, 404)
