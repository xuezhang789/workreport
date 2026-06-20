import os
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.models import ExportJob
from core.services.upload_service import UploadService


def cleanup_expired_export_jobs():
    now = timezone.now()
    cleaned_files = 0
    marked_failed = 0

    jobs = ExportJob.objects.filter(expires_at__lt=now)
    for job in jobs.iterator(chunk_size=200):
        if job.file_path and os.path.exists(job.file_path):
            try:
                os.remove(job.file_path)
                cleaned_files += 1
            except OSError:
                pass
        if job.status != 'failed':
            job.status = 'failed'
            job.message = '导出已过期 / Export expired'
            job.save(update_fields=['status', 'message', 'updated_at'])
            marked_failed += 1

    return {'files': cleaned_files, 'jobs': marked_failed}


def recover_stale_export_jobs(max_age_minutes=None):
    max_age_minutes = max_age_minutes or getattr(settings, 'EXPORT_JOB_STALE_MINUTES', 60)
    cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
    qs = ExportJob.objects.filter(status='running', updated_at__lt=cutoff)
    count = qs.update(
        status='failed',
        progress=0,
        message='Worker heartbeat lost; please enqueue the export again.',
        updated_at=timezone.now(),
    )
    return count


def run_runtime_maintenance():
    return {
        'uploads': UploadService.cleanup_expired_uploads(
            chunked_upload_hours=getattr(settings, 'UPLOAD_SESSION_TTL_HOURS', 24),
        ),
        'exports': cleanup_expired_export_jobs(),
        'stale_exports': recover_stale_export_jobs(),
    }
