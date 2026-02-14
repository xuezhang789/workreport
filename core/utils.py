import time
import os
import csv
import re
from io import StringIO
from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render
from django.contrib import messages
from django.conf import settings
from core.models import ExportJob, Profile
from core.permissions import has_manage_permission # Import from new location

# File Upload Settings
UPLOAD_MAX_SIZE = 50 * 1024 * 1024  # 50MB
UPLOAD_ALLOWED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.txt', '.md', '.csv',
    '.jpg', '.jpeg', '.png', '.gif',
    '.zip', '.rar', '.7z', '.tar', '.gz'
}

MANAGER_ROLES = {'mgr', 'pm'}

# has_manage_permission moved to core.permissions
# Keeping this for backward compatibility if other apps import it directly, 
# but they should migrate to core.permissions
# We imported it above, so it is available in this namespace.

def _throttle(request, key: str, min_interval=0.8):
    """简单接口节流，基于 session/key。 / Simple API throttle based on session/key."""
    now = time.monotonic()
    last = request.session.get(key)
    if last and now - last < min_interval:
        return True
    request.session[key] = now
    return False

def _admin_forbidden(request, message="需要管理员权限 / Admin access required"):
    messages.error(request, message)
    return render(request, '403.html', {'detail': message}, status=403)

def _friendly_forbidden(request, message):
    """统一的友好 403 返回，带双语提示。 / Unified friendly 403 response with bilingual message."""
    return render(request, '403.html', {'detail': message}, status=403)

def _validate_file(file):
    """
    Validates file size and extension.
    验证文件大小和扩展名。
    Returns (is_valid, error_message)
    """
    if file.size > UPLOAD_MAX_SIZE:
        return False, f"文件大小超过限制 (Max {UPLOAD_MAX_SIZE // (1024*1024)}MB): {file.name}"
        
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in UPLOAD_ALLOWED_EXTENSIONS:
        return False, f"不支持的文件类型: {ext}"
        
    return True, None

CSV_DANGEROUS_PREFIXES = ('=', '+', '-', '@', '\t')

def _sanitize_csv_cell(value):
    if value is None:
        return ''
    text = str(value)
    if text.startswith(CSV_DANGEROUS_PREFIXES):
        return "'" + text
    return text

def _stream_csv(rows, header):
    def generate():
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow([_sanitize_csv_cell(h) for h in header])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for row in rows:
            writer.writerow([_sanitize_csv_cell(col) for col in row])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    return generate()

def _create_export_job(user, export_type):
    expires = timezone.now() + timedelta(days=3)
    return ExportJob.objects.create(user=user, export_type=export_type, status='running', progress=10, expires_at=expires)

def _generate_export_file(job, header, rows_iterable):
    """生成 CSV 临时文件，更新 Job 状态，返回文件路径。 / Generate CSV temp file, update Job status, return file path."""
    import tempfile
    import csv as pycsv
    import os
    fd, path = tempfile.mkstemp(prefix=f'export_{job.export_type}_', suffix='.csv')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
        writer = pycsv.writer(f)
        writer.writerow([_sanitize_csv_cell(h) for h in header])
        total = 0
        for total, row in enumerate(rows_iterable, start=1):
            writer.writerow([_sanitize_csv_cell(col) for col in row])
            if total % 50 == 0:
                job.progress = min(95, job.progress + 5)
                job.save(update_fields=['progress', 'updated_at'])
        job.progress = 100
        job.status = 'done'
        job.file_path = path
        job.save(update_fields=['status', 'progress', 'file_path', 'updated_at'])
        
        # Notify user
        from reports.services.notification_service import send_notification
        send_notification(
            user=job.user,
            title="导出完成",
            message=f"您的导出任务 ({job.export_type}) 已完成，请前往导出中心下载。",
            notification_type='system',
            data={'job_id': job.id, 'link': f'/reports/export/jobs/{job.id}/download/'}
        )
        
    return path
