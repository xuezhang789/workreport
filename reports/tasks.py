from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from reports.models import ExportJob, DailyReport, Task, Project
from django.utils import timezone
from django.utils.dateparse import parse_date
import csv
import os
import tempfile

EXPORT_CHUNK_SIZE = 500
CSV_DANGEROUS_PREFIXES = ('=', '+', '-', '@', '\t')

def _sanitize_csv_cell(value):
    if value is None:
        return ''
    text = str(value)
    if text.startswith(CSV_DANGEROUS_PREFIXES):
        return "'" + text
    return text

@shared_task
def send_weekly_digest_task(recipient, stats):
    """
    Async wrapper for sending weekly digest email.
    """
    from reports.services.notifications import send_weekly_digest
    send_weekly_digest(recipient, stats)

@shared_task
def generate_export_file_task(job_id, export_type, params):
    """
    Async task to generate export file.
    """
    try:
        job = ExportJob.objects.get(id=job_id)
    except ExportJob.DoesNotExist:
        return

    job.status = 'running'
    job.progress = 5
    job.save(update_fields=['status', 'progress', 'updated_at'])

    try:
        rows_iterable = []
        header = []

        if export_type == 'admin_reports':
            role = params.get('role')
            start_date = parse_date(params.get('start_date') or '')
            end_date = parse_date(params.get('end_date') or '')
            username = params.get('username')
            project_id = params.get('project_id')

            qs = DailyReport.objects.select_related('user').prefetch_related('projects').order_by('-date', '-created_at')
            if role:
                qs = qs.filter(role=role)
            if start_date:
                qs = qs.filter(date__gte=start_date)
            if end_date:
                qs = qs.filter(date__lte=end_date)
            if username:
                qs = qs.filter(user__username__icontains=username)
            if project_id:
                qs = qs.filter(projects__id=project_id)

            header = ["日期", "角色", "项目", "用户", "状态", "摘要", "创建时间"]
            
            # Use iterator to avoid memory issues, but we need to fetch all for the loop or handle iterator carefully
            # Since this is a background task, we can afford a bit more time but should still be memory efficient.
            
            def report_iterator():
                for r in qs.iterator(chunk_size=EXPORT_CHUNK_SIZE):
                    yield [
                        str(r.date),
                        r.get_role_display(),
                        r.project_names or "",
                        r.user.get_full_name() or r.user.username,
                        r.get_status_display(),
                        r.summary or "",
                        timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
                    ]
            
            rows_iterable = report_iterator()

        # Generate File
        fd, path = tempfile.mkstemp(prefix=f'export_{job.export_type}_', suffix='.csv')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([_sanitize_csv_cell(h) for h in header])
            
            total_processed = 0
            for row in rows_iterable:
                writer.writerow([_sanitize_csv_cell(col) for col in row])
                total_processed += 1
                if total_processed % 50 == 0:
                    job.progress = min(95, 5 + int((total_processed / (total_processed + 100)) * 90)) # Rough progress
                    job.save(update_fields=['progress', 'updated_at'])

        job.progress = 100
        job.status = 'done'
        job.file_path = path
        job.save(update_fields=['status', 'progress', 'file_path', 'updated_at'])

    except Exception as e:
        job.status = 'failed'
        job.message = str(e)
        job.save(update_fields=['status', 'message', 'updated_at'])
        # Re-raise to let Celery know it failed (optional, depending on if we want retry)
        # raise e 
