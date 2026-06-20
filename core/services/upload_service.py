
import os
import logging
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename
from django.utils import timezone
from core.models import ChunkedUpload, DirectUpload
from core.utils import UPLOAD_MAX_SIZE, UPLOAD_ALLOWED_EXTENSIONS, _validate_file
from core.services.storage.router import RouterStorage

logger = logging.getLogger(__name__)

class UploadService:
    @staticmethod
    def sanitize_filename(filename):
        raw_name = (filename or '').replace('\\', '/')
        base_name = os.path.basename(raw_name).strip()
        if not base_name:
            return ''
        safe_name = get_valid_filename(base_name)
        return safe_name[:255]

    @staticmethod
    def validate_file_request(file_obj, max_size=UPLOAD_MAX_SIZE, allowed_extensions=UPLOAD_ALLOWED_EXTENSIONS):
        """
        Validates a file object (size, extension).
        Returns (is_valid, error_message)
        """
        return _validate_file(file_obj, max_size, allowed_extensions)

    @staticmethod
    def constraints_for_type(upload_type):
        from core.utils import AVATAR_ALLOWED_EXTENSIONS, AVATAR_MAX_SIZE

        max_size = UPLOAD_MAX_SIZE
        allowed_extensions = UPLOAD_ALLOWED_EXTENSIONS
        if upload_type == DirectUpload.UploadType.AVATAR:
            max_size = AVATAR_MAX_SIZE
            allowed_extensions = AVATAR_ALLOWED_EXTENSIONS
        elif upload_type == DirectUpload.UploadType.PROJECT:
            max_size = 10 * 1024 * 1024
        elif upload_type == DirectUpload.UploadType.TASK:
            max_size = 50 * 1024 * 1024
        return max_size, allowed_extensions

    @staticmethod
    def biz_type_for_upload(upload_type):
        return {
            DirectUpload.UploadType.PROJECT: 'project_attachment',
            DirectUpload.UploadType.TASK: 'task_attachment',
            DirectUpload.UploadType.AVATAR: 'default',
        }.get(upload_type, 'default')

    @staticmethod
    def storage_prefix_for_upload(upload_type):
        return {
            DirectUpload.UploadType.PROJECT: 'project_attachments',
            DirectUpload.UploadType.TASK: 'task_attachments',
            DirectUpload.UploadType.AVATAR: 'avatars',
        }.get(upload_type, 'uploads')

    @staticmethod
    def init_chunked_upload(user, filename, total_size, max_size=UPLOAD_MAX_SIZE, allowed_extensions=UPLOAD_ALLOWED_EXTENSIONS):
        """
        Initialize a chunked upload session.
        """
        filename = UploadService.sanitize_filename(filename)
        if not filename:
            return None, "Invalid filename"
        if total_size <= 0:
            return None, "File size must be greater than 0"
        if total_size > max_size:
            return None, f"File size exceeds limit ({max_size // (1024*1024)}MB)"
            
        ext = os.path.splitext(filename)[1].lower()
        if ext not in allowed_extensions:
            return None, f"Unsupported file type: {ext}"

        # Check for existing incomplete upload (Resume)
        # 检查是否存在未完成的上传（断点续传）
        existing = ChunkedUpload.objects.filter(
            user=user,
            filename=filename,
            file_size=total_size,
            status='uploading'
        ).order_by('-updated_at').first()

        if existing:
            # Check if temp file still exists
            if os.path.exists(existing.temp_path):
                # Verify actual size matches DB
                actual_size = os.path.getsize(existing.temp_path)
                if actual_size == existing.uploaded_size:
                    logger.info(f"Resuming upload {existing.id} for {filename}")
                    return existing, None
                else:
                    # Mismatch, reset
                    existing.uploaded_size = actual_size
                    existing.save(update_fields=['uploaded_size'])
                    return existing, None
            else:
                # File gone, delete record and start over
                existing.delete()

        # Create a unique temp file path
        # We use a dedicated temp directory for uploads
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
        os.makedirs(temp_dir, exist_ok=True)
            
        upload_id = uuid.uuid4()
        temp_path = os.path.join(temp_dir, f"{upload_id}_{filename}")
        
        # Create empty file
        with open(temp_path, 'wb') as f:
            pass
            
        chunk_upload = ChunkedUpload.objects.create(
            id=upload_id,
            user=user,
            filename=filename,
            file_size=total_size,
            temp_path=temp_path,
            status='uploading'
        )
        
        return chunk_upload, None

    @staticmethod
    def init_direct_upload(user, filename, total_size, upload_type='default', content_type=''):
        if not getattr(settings, 'DIRECT_UPLOAD_ENABLED', False):
            return None, None, "Direct upload is disabled"

        filename = UploadService.sanitize_filename(filename)
        if not filename:
            return None, None, "Invalid filename"
        if total_size <= 0:
            return None, None, "File size must be greater than 0"

        max_size, allowed_extensions = UploadService.constraints_for_type(upload_type)
        if total_size > max_size:
            return None, None, f"File size exceeds limit ({max_size // (1024*1024)}MB)"

        ext = os.path.splitext(filename)[1].lower()
        if ext not in allowed_extensions:
            return None, None, f"Unsupported file type: {ext}"

        biz_type = UploadService.biz_type_for_upload(upload_type)
        storage = RouterStorage(biz_type=biz_type)
        prefix = UploadService.storage_prefix_for_upload(upload_type)
        object_name = f"{prefix}/{uuid.uuid4().hex}_{filename}"
        expires_in = int(getattr(settings, 'DIRECT_UPLOAD_EXPIRES_SECONDS', 900))

        try:
            presigned = storage.create_direct_upload(
                object_name,
                content_type=content_type,
                expires_in=expires_in,
                max_size=max_size,
            )
        except NotImplementedError:
            return None, None, "Direct upload is not supported by the configured storage backend"

        upload = DirectUpload.objects.create(
            user=user,
            filename=filename,
            file_size=total_size,
            content_type=content_type or '',
            upload_type=upload_type,
            biz_type=biz_type,
            storage_path=presigned['storage_path'],
            expires_at=timezone.now() + timedelta(seconds=expires_in),
        )
        return upload, presigned, None

    @staticmethod
    def process_chunk(user, upload_id, chunk_index, chunk_data, offset=None):
        """
        Process a single chunk.
        If offset is provided, write to that offset. 
        Otherwise assume sequential appending (risky for concurrent, but simple JS usually does sequential).
        For robustness, we use 'seek'.
        """
        try:
            upload = ChunkedUpload.objects.get(id=upload_id, user=user)
        except (ChunkedUpload.DoesNotExist, ValidationError, ValueError, TypeError):
            return False, "Upload session not found"
            
        if upload.status != 'uploading':
            return False, f"Invalid status: {upload.status}"

        try:
            with open(upload.temp_path, 'r+b') as f:
                if offset is not None and offset < 0:
                    return False, "Invalid upload offset"
                if offset is not None:
                    write_offset = offset
                    f.seek(write_offset)
                else:
                    # Append mode if no offset (simplistic)
                    f.seek(0, 2)
                    write_offset = f.tell()

                chunk_bytes = chunk_data.read()
                next_size = write_offset + len(chunk_bytes)
                if next_size > upload.file_size:
                    return False, "Uploaded data exceeds declared file size"

                f.write(chunk_bytes)
                
            upload.uploaded_size = os.path.getsize(upload.temp_path)
            upload.chunk_count += 1
            upload.save(update_fields=['uploaded_size', 'chunk_count', 'updated_at'])
            
            return True, None
        except Exception as e:
            logger.error(f"Chunk upload failed: {e}")
            return False, str(e)

    @staticmethod
    def complete_chunked_upload(
        user,
        upload_id,
        max_size=UPLOAD_MAX_SIZE,
        allowed_extensions=UPLOAD_ALLOWED_EXTENSIONS,
    ):
        """
        Finalize the upload. Move temp file to final storage.
        Returns (FileObject, error_message)
        """
        try:
            upload = ChunkedUpload.objects.get(id=upload_id, user=user)
        except (ChunkedUpload.DoesNotExist, ValidationError, ValueError, TypeError):
            return None, "Upload session not found"

        if upload.status == 'failed':
            return None, "Invalid status: failed"

        if upload.uploaded_size != upload.file_size:
            return None, f"Size mismatch: expected {upload.file_size}, got {upload.uploaded_size}"

        # Read temp file and save to RouterStorage
        try:
            with open(upload.temp_path, 'rb') as f:
                content = ContentFile(f.read(), name=upload.filename)

            is_valid, validation_error = _validate_file(
                content,
                max_size=max_size,
                allowed_extensions=allowed_extensions,
            )
            if not is_valid:
                if os.path.exists(upload.temp_path):
                    os.remove(upload.temp_path)
                upload.status = 'failed'
                upload.save(update_fields=['status'])
                return None, validation_error
                
            # Cleanup temp file
            if os.path.exists(upload.temp_path):
                os.remove(upload.temp_path)
                
            upload.status = 'complete'
            upload.save(update_fields=['status'])
            
            return content, None
            
        except Exception as e:
            logger.error(f"Completion failed: {e}")
            upload.status = 'failed'
            upload.save(update_fields=['status'])
            return None, str(e)

    @staticmethod
    def complete_direct_upload(user, upload_id):
        try:
            upload = DirectUpload.objects.get(id=upload_id, user=user)
        except (DirectUpload.DoesNotExist, ValidationError, ValueError, TypeError):
            return None, "Upload session not found"

        if upload.status not in {DirectUpload.Status.PENDING, DirectUpload.Status.COMPLETE}:
            return None, f"Invalid status: {upload.status}"
        if upload.expires_at <= timezone.now():
            upload.status = DirectUpload.Status.FAILED
            upload.save(update_fields=['status', 'updated_at'])
            return None, "Upload session expired"

        storage = RouterStorage(biz_type=upload.biz_type)
        if not storage.exists(upload.storage_path):
            return None, "Uploaded object not found"

        actual_size = storage.size(upload.storage_path)
        if actual_size != upload.file_size:
            return None, f"Size mismatch: expected {upload.file_size}, got {actual_size}"

        upload.status = DirectUpload.Status.COMPLETE
        upload.completed_at = timezone.now()
        upload.save(update_fields=['status', 'completed_at', 'updated_at'])
        return upload, None

    @staticmethod
    def consume_direct_upload(user, upload_id, expected_upload_type):
        upload, error = UploadService.complete_direct_upload(user, upload_id)
        if error:
            return None, error
        if upload.upload_type != expected_upload_type:
            return None, "Upload type mismatch"
        if upload.status == DirectUpload.Status.ATTACHED:
            return None, "Upload already attached"
        return upload, None

    @staticmethod
    def mark_direct_upload_attached(upload):
        upload.status = DirectUpload.Status.ATTACHED
        upload.attached_at = timezone.now()
        upload.save(update_fields=['status', 'attached_at', 'updated_at'])
        return upload, None

    @staticmethod
    def handle_standard_upload(file_obj, max_size=UPLOAD_MAX_SIZE, allowed_extensions=UPLOAD_ALLOWED_EXTENSIONS):
        """
        Handle standard (non-chunked) upload.
        Just validates and returns the file object ready for saving.
        """
        is_valid, error = _validate_file(file_obj, max_size, allowed_extensions)
        if not is_valid:
            return None, error
        return file_obj, None

    @staticmethod
    def cleanup_expired_uploads(chunked_upload_hours=24):
        now = timezone.now()
        stale_chunked = ChunkedUpload.objects.filter(
            status__in=['uploading', 'failed'],
            updated_at__lt=now - timedelta(hours=chunked_upload_hours),
        )
        removed_chunked = 0
        for upload in stale_chunked.iterator(chunk_size=200):
            if upload.temp_path and os.path.exists(upload.temp_path):
                try:
                    os.remove(upload.temp_path)
                except OSError:
                    logger.warning("Failed to remove stale chunk upload %s", upload.temp_path, exc_info=True)
            upload.delete()
            removed_chunked += 1

        expired_direct = DirectUpload.objects.filter(
            status__in=[DirectUpload.Status.PENDING, DirectUpload.Status.COMPLETE, DirectUpload.Status.FAILED],
            expires_at__lt=now,
        )
        removed_direct = 0
        for upload in expired_direct.iterator(chunk_size=200):
            storage = RouterStorage(biz_type=upload.biz_type)
            try:
                if upload.storage_path and storage.exists(upload.storage_path):
                    storage.delete(upload.storage_path)
            except Exception:
                logger.warning("Failed to remove expired direct upload %s", upload.storage_path, exc_info=True)
            upload.delete()
            removed_direct += 1

        return {'chunked': removed_chunked, 'direct': removed_direct}
