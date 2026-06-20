import os
import shutil
from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import DirectUpload
from core.services.storage.backends import S3StorageHandler
from core.services.upload_service import UploadService


class ObjectNotFound(Exception):
    response = {'Error': {'Code': '404'}}


class DirectUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('direct-uploader', password='password')
        self.client.force_login(self.user)
        self.storage_config = {
            'default': 's3',
            'strategies': {
                'task_attachment': 's3',
                'project_attachment': 's3',
            },
            'backends': {
                's3': {
                    'type': 's3',
                    'OPTIONS': {
                        'bucket': 'direct-upload-bucket',
                        'region': 'us-east-1',
                    },
                },
            },
        }

    @override_settings(DIRECT_UPLOAD_ENABLED=True)
    def test_local_backend_rejects_direct_upload(self):
        response = self.client.post(
            reverse('core:upload_direct_init'),
            data='{"filename":"local.txt","size":4,"type":"task"}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('not supported', response.json()['message'])

    @override_settings(DIRECT_UPLOAD_ENABLED=True)
    def test_s3_direct_upload_lifecycle(self):
        fake_client = Mock()
        fake_client.head_object.side_effect = [
            ObjectNotFound(),
            {'ContentLength': 4},
            {'ContentLength': 4},
        ]
        fake_client.generate_presigned_post.return_value = {
            'url': 'https://upload.example',
            'fields': {'key': 's3/task_attachments/file.txt'},
        }

        with override_settings(ATTACHMENT_STORAGE_CONFIG=self.storage_config):
            with patch.object(S3StorageHandler, '_build_client', return_value=fake_client):
                upload, presigned, error = UploadService.init_direct_upload(
                    self.user,
                    'file.txt',
                    4,
                    upload_type=DirectUpload.UploadType.TASK,
                    content_type='text/plain',
                )
                self.assertIsNone(error)
                self.assertEqual(presigned['method'], 'POST')
                self.assertTrue(upload.storage_path.startswith('s3/task_attachments/'))

                completed, error = UploadService.complete_direct_upload(self.user, upload.id)

        self.assertIsNone(error)
        self.assertEqual(completed.status, DirectUpload.Status.COMPLETE)
        fake_client.generate_presigned_post.assert_called_once()

    @override_settings(DIRECT_UPLOAD_ENABLED=True)
    def test_direct_upload_api_returns_presigned_payload(self):
        fake_client = Mock()
        fake_client.head_object.side_effect = ObjectNotFound()
        fake_client.generate_presigned_post.return_value = {
            'url': 'https://upload.example',
            'fields': {'key': 's3/project_attachments/file.txt'},
        }

        with override_settings(ATTACHMENT_STORAGE_CONFIG=self.storage_config):
            with patch.object(S3StorageHandler, '_build_client', return_value=fake_client):
                response = self.client.post(
                    reverse('core:upload_direct_init'),
                    data='{"filename":"file.txt","size":4,"type":"project","content_type":"text/plain"}',
                    content_type='application/json',
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('upload', data)
        self.assertEqual(data['upload']['method'], 'POST')


class UploadMaintenanceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cleanup-user', password='password')
        self.media_root = '/tmp/workreport-direct-upload-cleanup'
        os.makedirs(os.path.join(self.media_root, 'local', 'uploads'), exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.media_root):
            shutil.rmtree(self.media_root)

    def test_cleanup_expired_direct_upload_removes_object_and_row(self):
        path = os.path.join(self.media_root, 'local', 'uploads', 'expired.txt')
        with open(path, 'wb') as file_obj:
            file_obj.write(b'expired')
        upload = DirectUpload.objects.create(
            user=self.user,
            filename='expired.txt',
            file_size=7,
            upload_type=DirectUpload.UploadType.DEFAULT,
            biz_type='default',
            storage_path='local/uploads/expired.txt',
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        storage_config = {
            'default': 'local',
            'backends': {
                'local': {
                    'type': 'local',
                    'OPTIONS': {'location': self.media_root, 'base_url': '/media/'},
                },
            },
        }
        with override_settings(MEDIA_ROOT=self.media_root, ATTACHMENT_STORAGE_CONFIG=storage_config):
            result = UploadService.cleanup_expired_uploads()

        self.assertEqual(result['direct'], 1)
        self.assertFalse(os.path.exists(path))
        self.assertFalse(DirectUpload.objects.filter(id=upload.id).exists())
