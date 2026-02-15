
import os
import shutil
from django.conf import settings
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
import logging

logger = logging.getLogger(__name__)

class BaseStorageHandler:
    def size(self, name):
        return os.path.getsize(self._get_path(name))

    def save(self, name, content, max_length=None):
        raise NotImplementedError
    
    def open(self, name, mode='rb'):
        raise NotImplementedError

    def url(self, name):
        raise NotImplementedError
    
    def exists(self, name):
        raise NotImplementedError
    
    def delete(self, name):
        raise NotImplementedError

    def path(self, name):
        raise NotImplementedError


class LocalStorageHandler(BaseStorageHandler):
    def __init__(self, config):
        self.location = config.get('location', os.path.join(settings.MEDIA_ROOT, 'local'))
        self.base_url = config.get('base_url', settings.MEDIA_URL + 'local/')
        if not os.path.exists(self.location):
            os.makedirs(self.location, exist_ok=True)

    def _get_path(self, name):
        # Prevent double prefixing if name already contains 'local/' and location is 'media/local'
        # The router passes 'local/filename.ext'.
        # We want to store it as 'media/local/filename.ext' (if we strip prefix)
        # OR 'media/local/local/filename.ext' (if we don't).
        # Let's keep it simple: storage location is root for this backend.
        # If router prefixes, it's a subdirectory.
        return os.path.join(self.location, name)

    def save(self, name, content, max_length=None):
        path = self._get_path(name)
        directory = os.path.dirname(path)
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            
        with open(path, 'wb') as f:
            for chunk in content.chunks():
                f.write(chunk)
        return name

    def open(self, name, mode='rb'):
        return open(self._get_path(name), mode)

    def url(self, name):
        # If name is 'local/file.jpg' and base_url is '/media/local/', result is '/media/local/local/file.jpg'
        # This might look weird but works if MEDIA_URL is served correctly.
        # Ideally, we should strip the backend prefix if base_url already implies it.
        # But 'name' stored in DB has the prefix.
        # Let's assume base_url is just MEDIA_URL.
        return settings.MEDIA_URL + name

    def exists(self, name):
        return os.path.exists(self._get_path(name))

    def delete(self, name):
        path = self._get_path(name)
        if os.path.exists(path):
            os.remove(path)

    def path(self, name):
        return self._get_path(name)


class S3StorageHandler(BaseStorageHandler):
    """
    Mock S3 Handler.
    """
    def __init__(self, config):
        self.bucket = config.get('bucket', 'my-bucket')
        self.region = config.get('region', 'us-east-1')
        self.mock_location = os.path.join(settings.MEDIA_ROOT, 's3_mock', self.bucket)
        if not os.path.exists(self.mock_location):
            os.makedirs(self.mock_location, exist_ok=True)
        logger.info(f"Initialized S3 Handler for bucket {self.bucket}")

    def save(self, name, content, max_length=None):
        logger.info(f"Uploading {name} to S3 bucket {self.bucket}...")
        path = os.path.join(self.mock_location, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            for chunk in content.chunks():
                f.write(chunk)
        return name

    def url(self, name):
        # name includes 's3/...' prefix from router? 
        # Yes, router passes 's3/file.jpg'.
        # S3 URL structure usually doesn't have 's3/' unless it's a folder.
        # So we construct URL: https://bucket.s3.region.amazonaws.com/s3/file.jpg
        return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{name}"

    def exists(self, name):
        return os.path.exists(os.path.join(self.mock_location, name))

    def size(self, name):
        return os.path.getsize(os.path.join(self.mock_location, name))

    def open(self, name, mode='rb'):
        return open(os.path.join(self.mock_location, name), mode)

    def delete(self, name):
        path = os.path.join(self.mock_location, name)
        if os.path.exists(path):
            os.remove(path)

class OSSStorageHandler(BaseStorageHandler):
    """
    Mock Aliyun OSS Handler.
    """
    def __init__(self, config):
        self.bucket = config.get('bucket', 'my-oss-bucket')
        self.endpoint = config.get('endpoint', 'oss-cn-hangzhou.aliyuncs.com')
        self.mock_location = os.path.join(settings.MEDIA_ROOT, 'oss_mock', self.bucket)
        if not os.path.exists(self.mock_location):
            os.makedirs(self.mock_location, exist_ok=True)
        logger.info(f"Initialized OSS Handler for bucket {self.bucket}")

    def save(self, name, content, max_length=None):
        logger.info(f"Uploading {name} to Aliyun OSS bucket {self.bucket}...")
        path = os.path.join(self.mock_location, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            for chunk in content.chunks():
                f.write(chunk)
        return name

    def url(self, name):
        return f"https://{self.bucket}.{self.endpoint}/{name}"

    def exists(self, name):
        return os.path.exists(os.path.join(self.mock_location, name))

    def size(self, name):
        return os.path.getsize(os.path.join(self.mock_location, name))

    def open(self, name, mode='rb'):
        return open(os.path.join(self.mock_location, name), mode)

    def delete(self, name):
        path = os.path.join(self.mock_location, name)
        if os.path.exists(path):
            os.remove(path)
