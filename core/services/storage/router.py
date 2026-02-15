
import os
from django.conf import settings
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible
from .backends import LocalStorageHandler, S3StorageHandler, OSSStorageHandler

@deconstructible
class RouterStorage(Storage):
    """
    A Django Storage class that routes to different backends based on configuration
    and path prefixes.
    """
    def __init__(self, biz_type='default'):
        self.biz_type = biz_type
        self._handlers = {}

    def _get_config(self):
        config = getattr(settings, 'ATTACHMENT_STORAGE_CONFIG', {}).copy()
        
        # Check SystemSetting for runtime overrides
        # 检查 SystemSetting 以获取运行时覆盖配置
        try:
            from core.models import SystemSetting
            import json
            
            setting = SystemSetting.objects.filter(key='attachment_storage_config').first()
            if setting and setting.value:
                db_config = json.loads(setting.value)
                
                # Merge overrides
                if 'default' in db_config:
                    config['default'] = db_config['default']
                if 'strategies' in db_config:
                    # Update strategies (e.g. switch 'task_attachment' to 's3')
                    config.setdefault('strategies', {}).update(db_config.get('strategies', {}))
                if 'backends' in db_config:
                    # Add or update backends
                    config.setdefault('backends', {}).update(db_config.get('backends', {}))
        except Exception:
            # Avoid crashing if DB is not ready or JSON is invalid
            pass
            
        return config

    def _create_handler(self, backend_name, backend_config):
        engine = backend_config.get('ENGINE')
        if engine:
            # Dynamic import
            module_name, class_name = engine.rsplit('.', 1)
            import importlib
            module = importlib.import_module(module_name)
            handler_class = getattr(module, class_name)
            return handler_class(backend_config.get('OPTIONS', {}))
        
        # Fallback to simple type check if ENGINE not provided
        type_name = backend_config.get('type', 'local')
        if type_name == 'local':
            return LocalStorageHandler(backend_config.get('OPTIONS', {}))
        elif type_name == 's3':
            return S3StorageHandler(backend_config.get('OPTIONS', {}))
        elif type_name == 'oss':
            return OSSStorageHandler(backend_config.get('OPTIONS', {}))
        return LocalStorageHandler({})

    def _get_handler_by_name(self, backend_name):
        if backend_name in self._handlers:
            return self._handlers[backend_name]
            
        config = self._get_config()
        backends_config = config.get('backends', {})
        backend_config = backends_config.get(backend_name)
        
        if not backend_config:
            # Fallback to local default if config missing
            backend_config = {'type': 'local'}
            
        handler = self._create_handler(backend_name, backend_config)
        self._handlers[backend_name] = handler
        return handler

    def _get_write_handler_name(self):
        config = self._get_config()
        strategies = config.get('strategies', {})
        return strategies.get(self.biz_type, config.get('default', 'local'))

    def _get_read_handler_name(self, name):
        """
        Determine handler based on path prefix.
        e.g. 's3/path/to/file.jpg' -> 's3'
        """
        config = self._get_config()
        parts = name.split('/', 1)
        if len(parts) > 1:
            prefix = parts[0]
            if prefix in config.get('backends', {}):
                return prefix
        # Fallback for legacy files
        return config.get('default', 'local')

    def get_available_name(self, name, max_length=None):
        """
        Returns a filename that's free on the target storage system, and
        available for new content to be written to.
        """
        backend_name = self._get_write_handler_name()
        handler = self._get_handler_by_name(backend_name)
        
        # We need to construct the full routed name to check existence
        # e.g. 's3/path/to/file.jpg'
        routed_name = f"{backend_name}/{name}"
        
        # If the handler has get_available_name, use it (removing prefix first if needed?)
        # Most handlers don't, they rely on 'exists'.
        # Let's implement standard Django logic here but routing aware.
        
        dir_name, file_name = os.path.split(name)
        file_root, file_ext = os.path.splitext(file_name)
        
        # If the filename already exists, add an underscore and a random 7 alphanumeric char string
        # before the extension.
        count = 0
        while handler.exists(routed_name) or (max_length and len(routed_name) > max_length):
            # file_move_safe logic: add random string
            # Django's default is to append _1, _2... or random string.
            # We prefer random string for concurrent safety.
            import secrets
            import string
            random_suffix = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(7))
            
            new_file_name = f"{file_root}_{random_suffix}{file_ext}"
            name = os.path.join(dir_name, new_file_name)
            routed_name = f"{backend_name}/{name}"
            count += 1
            if count > 100:
                raise ValueError("Could not find an available filename")
                
        return name

    def _save(self, name, content):
        backend_name = self._get_write_handler_name()
        handler = self._get_handler_by_name(backend_name)
        
        # Prefix the name with backend identifier to enable routing on read
        # e.g. 'task_attachments/file.jpg' -> 's3/task_attachments/file.jpg'
        # Check if already prefixed? No, usually Django passes clean relative name.
        
        final_name = f"{backend_name}/{name}"
        
        # The handler's save method should return the name that was saved.
        # We return this name to Django to store in the DB.
        return handler.save(final_name, content)

    def open(self, name, mode='rb'):
        backend_name = self._get_read_handler_name(name)
        handler = self._get_handler_by_name(backend_name)
        return handler.open(name, mode)

    def delete(self, name):
        backend_name = self._get_read_handler_name(name)
        handler = self._get_handler_by_name(backend_name)
        handler.delete(name)

    def exists(self, name):
        backend_name = self._get_read_handler_name(name)
        handler = self._get_handler_by_name(backend_name)
        return handler.exists(name)

    def size(self, name):
        backend_name = self._get_read_handler_name(name)
        handler = self._get_handler_by_name(backend_name)
        if hasattr(handler, 'size'):
            return handler.size(name)
        raise NotImplementedError("Subclasses of Storage must provide a size() method")

    def url(self, name):
        backend_name = self._get_read_handler_name(name)
        handler = self._get_handler_by_name(backend_name)
        return handler.url(name)

    def path(self, name):
        backend_name = self._get_read_handler_name(name)
        handler = self._get_handler_by_name(backend_name)
        if hasattr(handler, 'path'):
            return handler.path(name)
        raise NotImplementedError("This backend doesn't support absolute paths.")
