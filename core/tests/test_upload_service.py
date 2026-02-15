from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from core.services.upload_service import UploadService
from core.models import ChunkedUpload
import os
import shutil

@override_settings(MEDIA_ROOT='/tmp/django_test_media')
class UploadServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.temp_dir = '/tmp/django_test_media'
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_chunked_upload_flow(self):
        # 1. Init
        filename = 'test_large_file.txt'
        content = b'HelloWorld' * 1024 * 1024 # 10MB
        size = len(content)
        
        upload, error = UploadService.init_chunked_upload(self.user, filename, size)
        self.assertIsNone(error)
        self.assertIsNotNone(upload)
        self.assertEqual(upload.status, 'uploading')
        
        # 2. Process Chunks (2 chunks)
        chunk_size = 5 * 1024 * 1024 # 5MB
        
        # Chunk 1
        chunk1 = ContentFile(content[:chunk_size], name='chunk1')
        success, error = UploadService.process_chunk(upload.id, 0, chunk1, offset=0)
        self.assertTrue(success)
        self.assertIsNone(error)
        
        # Chunk 2
        chunk2 = ContentFile(content[chunk_size:], name='chunk2')
        success, error = UploadService.process_chunk(upload.id, 1, chunk2, offset=chunk_size)
        self.assertTrue(success)
        self.assertIsNone(error)
        
        # Reload to check size
        upload.refresh_from_db()
        self.assertEqual(upload.uploaded_size, size)
        
        # 3. Complete
        final_file, error = UploadService.complete_chunked_upload(upload.id)
        self.assertIsNone(error)
        self.assertIsNotNone(final_file)
        
        # Verify content
        final_content = final_file.read()
        self.assertEqual(final_content, content)
        
        # Verify cleanup
        self.assertFalse(os.path.exists(upload.temp_path))
        
        # Verify status
        upload.refresh_from_db()
        self.assertEqual(upload.status, 'complete')

    def test_invalid_init(self):
        # Too large
        upload, error = UploadService.init_chunked_upload(self.user, 'test.txt', 10**10)
        self.assertIsNotNone(error)
        self.assertIsNone(upload)

    def test_process_chunk_invalid_id(self):
        import uuid
        success, error = UploadService.process_chunk(uuid.uuid4(), 0, ContentFile(b'test'))
        self.assertFalse(success)
