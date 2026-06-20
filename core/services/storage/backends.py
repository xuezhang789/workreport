
import os
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
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

    def create_presigned_upload(self, name, content_type='', expires_in=300, max_size=None):
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

    def create_presigned_upload(self, name, content_type='', expires_in=300, max_size=None):
        raise NotImplementedError('Local storage does not support direct upload')


class S3StorageHandler(BaseStorageHandler):
    """Private Amazon S3-compatible object storage handler."""
    def __init__(self, config):
        self.bucket = config.get('bucket')
        if not self.bucket:
            raise ImproperlyConfigured('S3 storage requires a bucket name')
        self.region = config.get('region', 'us-east-1')
        self.endpoint_url = config.get('endpoint_url') or None
        self.access_key = config.get('access_key') or None
        self.secret_key = config.get('secret_key') or None
        self.session_token = config.get('session_token') or None
        self.addressing_style = config.get('addressing_style', 'auto')
        self.signature_version = config.get('signature_version', 's3v4')
        self.url_expiry = int(config.get('url_expiry', 300))
        self.server_side_encryption = config.get('server_side_encryption') or None
        self.client = self._build_client()

    def _build_client(self):
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:
            raise ImproperlyConfigured('S3 storage requires the boto3 package') from exc

        kwargs = {
            'service_name': 's3',
            'region_name': self.region,
            'endpoint_url': self.endpoint_url,
            'config': Config(
                signature_version=self.signature_version,
                s3={'addressing_style': self.addressing_style},
            ),
        }
        if self.access_key:
            kwargs['aws_access_key_id'] = self.access_key
        if self.secret_key:
            kwargs['aws_secret_access_key'] = self.secret_key
        if self.session_token:
            kwargs['aws_session_token'] = self.session_token
        return boto3.client(**kwargs)

    def save(self, name, content, max_length=None):
        content.seek(0)
        extra_args = {}
        content_type = getattr(content, 'content_type', None)
        if content_type:
            extra_args['ContentType'] = content_type
        if self.server_side_encryption:
            extra_args['ServerSideEncryption'] = self.server_side_encryption
        self.client.upload_fileobj(
            content,
            self.bucket,
            name,
            ExtraArgs=extra_args or None,
        )
        return name

    def url(self, name):
        return self.client.generate_presigned_url(
            'get_object',
            Params={'Bucket': self.bucket, 'Key': name},
            ExpiresIn=self.url_expiry,
        )

    def exists(self, name):
        try:
            self.client.head_object(Bucket=self.bucket, Key=name)
            return True
        except Exception as exc:
            response = getattr(exc, 'response', {})
            code = str(response.get('Error', {}).get('Code', ''))
            if code in {'404', 'NoSuchKey', 'NotFound'}:
                return False
            raise

    def size(self, name):
        response = self.client.head_object(Bucket=self.bucket, Key=name)
        return response['ContentLength']

    def open(self, name, mode='rb'):
        if mode not in {'r', 'rb'}:
            raise ValueError('S3 objects can only be opened for reading')
        return self.client.get_object(Bucket=self.bucket, Key=name)['Body']

    def delete(self, name):
        self.client.delete_object(Bucket=self.bucket, Key=name)

    def create_presigned_upload(self, name, content_type='', expires_in=300, max_size=None):
        fields = {}
        conditions = []
        if content_type:
            fields['Content-Type'] = content_type
            conditions.append({'Content-Type': content_type})
        if max_size:
            conditions.append(['content-length-range', 1, max_size])
        if self.server_side_encryption:
            fields['x-amz-server-side-encryption'] = self.server_side_encryption
            conditions.append({'x-amz-server-side-encryption': self.server_side_encryption})

        post = self.client.generate_presigned_post(
            Bucket=self.bucket,
            Key=name,
            Fields=fields or None,
            Conditions=conditions or None,
            ExpiresIn=expires_in,
        )
        return {
            'method': 'POST',
            'url': post['url'],
            'fields': post.get('fields', {}),
            'headers': {},
            'object_key': name,
            'expires_in': expires_in,
        }

class OSSStorageHandler(BaseStorageHandler):
    """Private Aliyun OSS object storage handler."""
    def __init__(self, config):
        self.bucket_name = config.get('bucket')
        self.endpoint = config.get('endpoint')
        self.access_key = config.get('access_key')
        self.secret_key = config.get('secret_key')
        self.url_expiry = int(config.get('url_expiry', 300))
        if not all((self.bucket_name, self.endpoint, self.access_key, self.secret_key)):
            raise ImproperlyConfigured('OSS storage requires bucket, endpoint, access_key, and secret_key')
        if not self.endpoint.startswith(('http://', 'https://')):
            self.endpoint = f'https://{self.endpoint}'
        self.bucket = self._build_bucket()

    def _build_bucket(self):
        try:
            import oss2
        except ImportError as exc:
            raise ImproperlyConfigured('OSS storage requires the oss2 package') from exc
        auth = oss2.Auth(self.access_key, self.secret_key)
        return oss2.Bucket(auth, self.endpoint, self.bucket_name)

    def save(self, name, content, max_length=None):
        content.seek(0)
        self.bucket.put_object(name, content)
        return name

    def url(self, name):
        return self.bucket.sign_url('GET', name, self.url_expiry)

    def exists(self, name):
        return self.bucket.object_exists(name)

    def size(self, name):
        return self.bucket.get_object_meta(name).content_length

    def open(self, name, mode='rb'):
        if mode not in {'r', 'rb'}:
            raise ValueError('OSS objects can only be opened for reading')
        return self.bucket.get_object(name)

    def delete(self, name):
        self.bucket.delete_object(name)

    def create_presigned_upload(self, name, content_type='', expires_in=300, max_size=None):
        headers = {}
        if content_type:
            headers['Content-Type'] = content_type
        return {
            'method': 'PUT',
            'url': self.bucket.sign_url('PUT', name, expires_in, headers=headers),
            'fields': {},
            'headers': headers,
            'object_key': name,
            'expires_in': expires_in,
        }
