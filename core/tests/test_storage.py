
from django.test import TestCase, override_settings
from django.core.files.base import ContentFile
from django.conf import settings
from core.services.storage.router import RouterStorage
from core.services.storage.backends import S3StorageHandler, OSSStorageHandler
from core.models import SystemSetting
import os
import shutil
import json
from unittest.mock import Mock, patch


class ObjectNotFound(Exception):
    response = {'Error': {'Code': '404'}}

class StorageRouterTest(TestCase):
    def setUp(self):
        # Setup temporary media root
        self.test_media_root = os.path.join(settings.BASE_DIR, 'test_media_storage')
        self.local_root = os.path.join(self.test_media_root, 'local')
        self.s3_mock_root = os.path.join(self.test_media_root, 's3_mock')
        
        if not os.path.exists(self.test_media_root):
            os.makedirs(self.test_media_root)

        # Define test config
        self.test_config = {
            'default': 'local',
            'strategies': {
                'test_biz': 'local',
            },
            'backends': {
                'local': {
                    'type': 'local',
                    'OPTIONS': {
                        'location': self.test_media_root,
                        'base_url': '/media/',
                    }
                },
                's3': {
                    'type': 's3',
                    'OPTIONS': {
                        'bucket': 'test-bucket',
                        'region': 'us-east-1', 
                    }
                }
            }
        }

    def tearDown(self):
        # Cleanup
        if os.path.exists(self.test_media_root):
            shutil.rmtree(self.test_media_root)

    def test_local_storage_routing(self):
        """Test routing to local storage based on settings."""
        with override_settings(ATTACHMENT_STORAGE_CONFIG=self.test_config):
            storage = RouterStorage(biz_type='test_biz')
            
            # Save file
            name = storage.save('test_file.txt', ContentFile(b'hello world'))
            
            expected_name = 'local/test_file.txt'
            self.assertEqual(name, expected_name)
            
            # Verify file exists on disk
            full_path = os.path.join(self.test_media_root, expected_name)
            self.assertTrue(os.path.exists(full_path))
            
            # Verify content
            with open(full_path, 'rb') as f:
                self.assertEqual(f.read(), b'hello world')
                
            # Verify URL
            url = storage.url(name)
            self.assertEqual(url, '/media/local/test_file.txt')

    def test_dynamic_switching_via_db(self):
        """Test switching storage backend at runtime via SystemSetting."""
        with override_settings(ATTACHMENT_STORAGE_CONFIG=self.test_config):
            # 1. Verify default is local
            storage = RouterStorage(biz_type='test_biz')
            self.assertEqual(storage._get_write_handler_name(), 'local')
            
            # 2. Override via DB to use S3
            override_config = {
                'strategies': {
                    'test_biz': 's3'
                }
            }
            
            SystemSetting.objects.create(
                key='attachment_storage_config',
                value=json.dumps(override_config)
            )
            
            # 3. Verify router now picks S3
            fake_client = Mock()
            fake_client.head_object.side_effect = ObjectNotFound()
            with patch.object(S3StorageHandler, '_build_client', return_value=fake_client):
                handler_name = storage._get_write_handler_name()
                self.assertEqual(handler_name, 's3')
                
                # Save file
                name = storage.save('s3_file.txt', ContentFile(b's3 content'))
                
                # Should be prefixed 's3/s3_file.txt'
                self.assertEqual(name, 's3/s3_file.txt')
                
                fake_client.upload_fileobj.assert_called_once()
                call = fake_client.upload_fileobj.call_args
                self.assertEqual(call.args[1:3], ('test-bucket', 's3/s3_file.txt'))

    def test_s3_handler_uses_private_object_operations(self):
        fake_client = Mock()
        fake_client.head_object.return_value = {'ContentLength': 42}
        fake_client.generate_presigned_url.return_value = 'https://signed.example/object'
        body = ContentFile(b'cloud content')
        fake_client.get_object.return_value = {'Body': body}

        with patch.object(S3StorageHandler, '_build_client', return_value=fake_client):
            handler = S3StorageHandler({'bucket': 'private-bucket', 'region': 'us-east-1'})
            handler.save('s3/report.txt', ContentFile(b'cloud content'))

            self.assertTrue(handler.exists('s3/report.txt'))
            self.assertEqual(handler.size('s3/report.txt'), 42)
            self.assertEqual(handler.url('s3/report.txt'), 'https://signed.example/object')
            self.assertEqual(handler.open('s3/report.txt').read(), b'cloud content')
            handler.delete('s3/report.txt')

        fake_client.delete_object.assert_called_once_with(Bucket='private-bucket', Key='s3/report.txt')

    def test_oss_handler_uses_private_object_operations(self):
        fake_bucket = Mock()
        fake_bucket.object_exists.return_value = True
        fake_bucket.get_object_meta.return_value.content_length = 21
        fake_bucket.sign_url.return_value = 'https://signed.oss.example/object'
        fake_bucket.get_object.return_value = ContentFile(b'oss content')

        with patch.object(OSSStorageHandler, '_build_bucket', return_value=fake_bucket):
            handler = OSSStorageHandler({
                'bucket': 'private-bucket',
                'endpoint': 'oss-cn-hangzhou.aliyuncs.com',
                'access_key': 'key',
                'secret_key': 'secret',
            })
            handler.save('oss/report.txt', ContentFile(b'oss content'))

            self.assertTrue(handler.exists('oss/report.txt'))
            self.assertEqual(handler.size('oss/report.txt'), 21)
            self.assertEqual(handler.url('oss/report.txt'), 'https://signed.oss.example/object')
            self.assertEqual(handler.open('oss/report.txt').read(), b'oss content')
            handler.delete('oss/report.txt')

        fake_bucket.delete_object.assert_called_once_with('oss/report.txt')

    def test_size_method(self):
        """Test that size() method is implemented and works."""
        with override_settings(ATTACHMENT_STORAGE_CONFIG=self.test_config):
            storage = RouterStorage(biz_type='test_biz')
            filename = 'test_size.txt'
            content = b'hello world'
            name = storage.save(filename, ContentFile(content))
            
            # Verify size
            try:
                size = storage.size(name)
                self.assertEqual(size, len(content))
            except NotImplementedError:
                self.fail("RouterStorage.size() raised NotImplementedError")

        """Test reading files routes to correct backend based on prefix."""
        with override_settings(ATTACHMENT_STORAGE_CONFIG=self.test_config):
            storage = RouterStorage()
            
            # 1. Local file
            local_name = 'local/foo.txt'
            handler_name = storage._get_read_handler_name(local_name)
            self.assertEqual(handler_name, 'local')
            
            # 2. S3 file
            s3_name = 's3/bar.txt'
            handler_name = storage._get_read_handler_name(s3_name)
            self.assertEqual(handler_name, 's3')
            
            # 3. Legacy file (no known prefix)
            legacy_name = 'legacy.txt'
            handler_name = storage._get_read_handler_name(legacy_name)
            self.assertEqual(handler_name, 'local') # Default

    def test_duplicate_filename_handling(self):
        """Test that uploading a file with existing name generates a new unique name."""
        with override_settings(ATTACHMENT_STORAGE_CONFIG=self.test_config):
            storage = RouterStorage(biz_type='test_biz')
            
            # 1. Create first file
            name1 = storage.save('duplicate.txt', ContentFile(b'first'))
            self.assertEqual(name1, 'local/duplicate.txt')
            
            # 2. Create second file with SAME name
            name2 = storage.save('duplicate.txt', ContentFile(b'second'))
            
            # 3. Verify name2 is different (e.g., duplicate_Abc1234.txt)
            self.assertNotEqual(name1, name2)
            self.assertTrue(name2.startswith('local/duplicate_'))
            self.assertTrue(name2.endswith('.txt'))
            
            # 4. Verify contents are preserved
            with storage.open(name1) as f1:
                self.assertEqual(f1.read(), b'first')
                
            with storage.open(name2) as f2:
                self.assertEqual(f2.read(), b'second')
