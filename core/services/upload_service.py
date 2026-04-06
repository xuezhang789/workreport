
import os
import logging
import uuid
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename
from core.models import ChunkedUpload
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
    def process_chunk(upload_id, chunk_index, chunk_data, offset=None):
        """
        Process a single chunk.
        If offset is provided, write to that offset. 
        Otherwise assume sequential appending (risky for concurrent, but simple JS usually does sequential).
        For robustness, we use 'seek'.
        """
        try:
            upload = ChunkedUpload.objects.get(id=upload_id)
        except ChunkedUpload.DoesNotExist:
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
    def complete_chunked_upload(upload_id):
        """
        Finalize the upload. Move temp file to final storage.
        Returns (FileObject, error_message)
        """
        try:
            upload = ChunkedUpload.objects.get(id=upload_id)
        except ChunkedUpload.DoesNotExist:
            return None, "Upload session not found"

        if upload.uploaded_size != upload.file_size:
            return None, f"Size mismatch: expected {upload.file_size}, got {upload.uploaded_size}"

        # Read temp file and save to RouterStorage
        try:
            with open(upload.temp_path, 'rb') as f:
                content = ContentFile(f.read(), name=upload.filename)
                
            # We don't save to model here, just return the file content 
            # so the caller (View) can save it to TaskAttachment/ProjectAttachment/etc.
            # But wait, RouterStorage needs to save it.
            
            # The view expects a Django File object to save into a FileField.
            # If we assign ContentFile to a FileField, Django saves it using the field's storage.
            
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
    def handle_standard_upload(file_obj, max_size=UPLOAD_MAX_SIZE, allowed_extensions=UPLOAD_ALLOWED_EXTENSIONS):
        """
        Handle standard (non-chunked) upload.
        Just validates and returns the file object ready for saving.
        """
        is_valid, error = _validate_file(file_obj, max_size, allowed_extensions)
        if not is_valid:
            return None, error
        return file_obj, None
