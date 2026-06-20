from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from core.models import ExportJob, Notification
from tasks.models import Task
from work_logs.models import DailyReport
from audit.services import archive_old_audit_logs
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db.models import Q
from core.services.task_locks import task_lock

EXPORT_CHUNK_SIZE = 500
CSV_DANGEROUS_PREFIXES = ('=', '+', '-', '@', '\t')
DEFAULT_TASK_KWARGS = {
    'acks_late': True,
    'reject_on_worker_lost': True,
    'soft_time_limit': getattr(settings, 'CELERY_TASK_SOFT_TIME_LIMIT', 300),
    'time_limit': getattr(settings, 'CELERY_TASK_TIME_LIMIT', 360),
}
LOCK_TIMEOUT = getattr(settings, 'CELERY_TASK_LOCK_TIMEOUT_SECONDS', 600)


@shared_task(**DEFAULT_TASK_KWARGS)
def process_notification_delivery_task(delivery_id):
    from core.services.notification_delivery import process_delivery
    return process_delivery(delivery_id)


@shared_task(**DEFAULT_TASK_KWARGS)
def dispatch_pending_notification_deliveries_task(limit=100):
    from core.services.notification_delivery import dispatch_pending_deliveries
    with task_lock('dispatch_pending_notification_deliveries', timeout=55) as acquired:
        if not acquired:
            return {'skipped': 'locked'}
        return dispatch_pending_deliveries(limit=limit)

def _sanitize_csv_cell(value):
    if value is None:
        return ''
    text = str(value)
    if text.startswith(CSV_DANGEROUS_PREFIXES):
        return "'" + text
    return text

@shared_task(**DEFAULT_TASK_KWARGS)
def cleanup_old_logs_task(days=180):
    """
    归档旧的 AuditLog 并清理 Notification 记录。
    默认保留最近 180 天的日志。
    """
    with task_lock('cleanup_old_logs', timeout=LOCK_TIMEOUT) as acquired:
        if not acquired:
            return {'skipped': 'locked'}

        cutoff_date = timezone.now() - timedelta(days=days)

        # Archive AuditLog before removing rows from the hot table.
        audit_result = archive_old_audit_logs(days=days)

        # 清理 Notification (通知通常可以保留更短时间，例如 90 天，这里统一使用 days 参数)
        # 对于未读通知，也许可以保留更久？目前策略是一视同仁。
        notif_count, _ = Notification.objects.filter(created_at__lt=cutoff_date).delete()

        return (
            f"Archived {audit_result['archived']} AuditLogs, "
            f"deleted {audit_result['deleted']} hot AuditLogs and {notif_count} Notifications "
            f"older than {days} days."
        )

@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_jitter=True, max_retries=3, **DEFAULT_TASK_KWARGS)
def send_email_async_task(subject, message, from_email, recipient_list, html_message=None):
    """
    异步发送邮件的 Celery 任务。
    添加了重试机制：失败时自动重试 3 次，指数退避。
    """
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=recipient_list,
            html_message=html_message,
            fail_silently=False  # Allow Celery to catch exceptions
        )
        return f"Email sent to {recipient_list}"
    except Exception as e:
        # 记录错误，也可以根据需要配置重试机制
        # Celery autoretry_for will handle retry
        raise e

@shared_task(**DEFAULT_TASK_KWARGS)
def send_weekly_digest_task(recipient, stats):
    """
    Deprecated: Use send_weekly_digest_email logic directly or new batch task.
    """
    pass

@shared_task(**DEFAULT_TASK_KWARGS)
def send_weekly_digests_batch():
    """
    自动批量发送周报（针对已订阅用户）。
    计划任务应配置为每周一凌晨运行。
    """
    from django.contrib.auth import get_user_model
    from core.constants import TaskStatus
    from reports.services.notification_service import send_weekly_digest_email
    
    with task_lock('send_weekly_digests_batch', timeout=LOCK_TIMEOUT) as acquired:
        if not acquired:
            return {'skipped': 'locked'}

        User = get_user_model()
        users = User.objects.filter(is_active=True).exclude(email='').select_related('preferences')
        count = 0
        
        for user in users:
            if not getattr(user, 'preferences', None):
                continue
            if not user.preferences.data.get('notify', {}).get('email_digest', False):
                continue

            try:
                user_tasks = Task.objects.filter(user=user)
                total = user_tasks.count()
                completed = user_tasks.filter(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]).count()
                overdue = user_tasks.filter(
                    status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW],
                    due_at__lt=timezone.now(),
                ).count()
                user_specific_stats = {
                    'overall_total': total,
                    'overall_completed': completed,
                    'overall_overdue': overdue,
                    'overall_rate': (completed / total * 100) if total else 0,
                    'project_stats': [],
                }
                send_weekly_digest_email(user, user_specific_stats)
                count += 1
            except Exception as exc:
                print(f"Failed to process digest for {user.username}: {exc}")

        return f"Sent {count} weekly digests."

def _admin_reports_export(job, params):
    from core.permissions import has_manage_permission
    from core.utils import _generate_export_file
    from reports.utils import get_accessible_projects

    if not has_manage_permission(job.user):
        raise PermissionError('Export permission was revoked')

    role = params.get('role')
    start_date = parse_date(params.get('start_date') or '')
    end_date = parse_date(params.get('end_date') or '')
    username = (params.get('username') or '').strip()
    project_id = params.get('project_id')
    status = params.get('status')

    qs = DailyReport.objects.select_related('user').prefetch_related('projects').order_by('-date', '-created_at')
    if not job.user.is_superuser:
        qs = qs.filter(projects__in=get_accessible_projects(job.user)).distinct()
    if role:
        qs = qs.filter(role=role)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    if username:
        qs = qs.filter(
            Q(user__username__icontains=username) |
            Q(user__first_name__icontains=username) |
            Q(user__last_name__icontains=username)
        )
    if project_id and str(project_id).isdigit():
        qs = qs.filter(projects__id=int(project_id))
    if status in dict(DailyReport.STATUS_CHOICES):
        qs = qs.filter(status=status)

    rows = (
        [
            str(report.date),
            report.get_role_display(),
            report.project_names or '',
            report.user.get_full_name() or report.user.username,
            report.get_status_display(),
            report.summary or '',
            timezone.localtime(report.created_at).strftime('%Y-%m-%d %H:%M'),
        ]
        for report in qs.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    return _generate_export_file(
        job,
        ["日期", "角色", "项目", "用户", "状态", "摘要", "创建时间"],
        rows,
    )


def _task_export(job, params, *, admin):
    from core.utils import _generate_export_file
    from reports.utils import get_accessible_projects, get_manageable_projects
    from tasks.services.export import TaskExportService
    from tasks.services.sla import calculate_sla_info

    qs = Task.objects.select_related('project', 'user', 'user__profile', 'sla_timer').prefetch_related('collaborators')
    if admin:
        projects = get_manageable_projects(job.user)
        if not projects.exists():
            raise PermissionError('Export permission was revoked')
        qs = qs.filter(project__in=projects)
    else:
        accessible_projects = get_accessible_projects(job.user)
        qs = qs.filter(project__in=accessible_projects)
        if not job.user.is_superuser:
            manageable_projects = get_manageable_projects(job.user)
            qs = qs.filter(
                Q(user=job.user) |
                Q(collaborators=job.user) |
                Q(project__in=manageable_projects)
            ).distinct()

    status = params.get('status')
    priority = params.get('priority')
    project_id = params.get('project_id')
    user_id = params.get('user_id')
    q = (params.get('q') or '').strip()
    if status in dict(Task.STATUS_CHOICES):
        qs = qs.filter(status=status)
    if priority in dict(Task.PRIORITY_CHOICES):
        qs = qs.filter(priority=priority)
    if project_id and str(project_id).isdigit():
        qs = qs.filter(project_id=int(project_id))
    if admin and user_id and str(user_id).isdigit():
        qs = qs.filter(user_id=int(user_id))
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q))

    allowed_sorts = {
        'created_at', '-created_at', 'priority', '-priority', 'status', '-status',
        'due_at', '-due_at', 'title', '-title',
    }
    sort_by = params.get('sort', '-created_at') if admin else '-created_at'
    qs = qs.order_by(sort_by if sort_by in allowed_sorts else '-created_at')

    tasks = qs
    if params.get('hot'):
        tasks = [
            task for task in qs
            if calculate_sla_info(task).get('status') in ('tight', 'overdue')
        ]

    return _generate_export_file(
        job,
        TaskExportService.get_header(),
        TaskExportService.get_export_rows(tasks),
    )


@shared_task(bind=True, max_retries=3, retry_backoff=True, retry_jitter=True, **DEFAULT_TASK_KWARGS)
def generate_export_file_task(self, job_id, export_type, params):
    """
    生成导出文件的异步任务。
    """
    try:
        job = ExportJob.objects.get(id=job_id)
    except ExportJob.DoesNotExist:
        return

    if job.status == 'done':
        return job.file_path

    job.status = 'running'
    job.progress = 5
    job.save(update_fields=['status', 'progress', 'updated_at'])

    try:
        if export_type == 'admin_reports_filtered':
            return _admin_reports_export(job, params)
        if export_type == 'admin_tasks':
            return _task_export(job, params, admin=True)
        if export_type == 'my_tasks':
            return _task_export(job, params, admin=False)
        raise ValueError(f'Unsupported export type: {export_type}')

    except Exception as e:
        if self.request.retries < self.max_retries:
            job.status = 'pending'
            job.message = f'Retrying after error: {e}'
            job.save(update_fields=['status', 'message', 'updated_at'])
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
        job.status = 'failed'
        job.message = str(e)
        job.save(update_fields=['status', 'message', 'updated_at'])
        raise


@shared_task(**DEFAULT_TASK_KWARGS)
def runtime_maintenance_task():
    from core.services.maintenance import run_runtime_maintenance

    with task_lock('runtime_maintenance', timeout=LOCK_TIMEOUT) as acquired:
        if not acquired:
            return {'skipped': 'locked'}
        return run_runtime_maintenance()
