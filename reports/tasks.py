from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from reports.models import ExportJob, DailyReport, Task, Project, Notification
from audit.models import AuditLog
from datetime import timedelta
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
def cleanup_old_logs_task(days=180):
    """
    清理旧的 AuditLog 和 Notification 记录。
    默认保留最近 180 天的日志。
    """
    cutoff_date = timezone.now() - timedelta(days=days)
    
    # 清理 AuditLog
    audit_count, _ = AuditLog.objects.filter(created_at__lt=cutoff_date).delete()
    
    # 清理 Notification (通知通常可以保留更短时间，例如 90 天，这里统一使用 days 参数)
    # 对于未读通知，也许可以保留更久？目前策略是一视同仁。
    notif_count, _ = Notification.objects.filter(created_at__lt=cutoff_date).delete()
    
    return f"Cleaned up {audit_count} AuditLogs and {notif_count} Notifications older than {days} days."

@shared_task(autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
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

@shared_task
def send_weekly_digest_task(recipient, stats):
    """
    Deprecated: Use send_weekly_digest_email logic directly or new batch task.
    """
    pass

@shared_task
def send_weekly_digests_batch():
    """
    自动批量发送周报（针对已订阅用户）。
    计划任务应配置为每周一凌晨运行。
    """
    from django.contrib.auth import get_user_model
    from reports.services.stats import get_performance_stats
    from reports.services.notification_service import send_weekly_digest_email
    from datetime import timedelta
    
    User = get_user_model()
    # 查找所有启用了 email_digest 的用户
    # 注意：JSONField 查询取决于数据库支持（SQLite 支持 JSON_EXTRACT 但 Django 语法可能有差异）
    # 为兼容性，先获取所有用户再在 Python 中过滤（如果用户量巨大需优化）
    
    users = User.objects.filter(is_active=True).exclude(email='').select_related('preferences')
    
    count = 0
    today = timezone.localdate()
    # 上周一到上周日
    start_date = today - timedelta(days=today.weekday() + 7)
    end_date = start_date + timedelta(days=6)
    
    for user in users:
        # Check preference
        allow_digest = False
        if hasattr(user, 'preferences'):
            allow_digest = user.preferences.data.get('notify', {}).get('email_digest', False)
        
        if allow_digest and user.email:
            # Generate stats for this user
            # 注意：performance_stats 计算较重，对于大量用户需谨慎
            # 简化版：只统计该用户的任务
            try:
                stats = get_performance_stats(
                    start_date=start_date,
                    end_date=end_date,
                    project_id=None,
                    role_filter=None,
                    q=None,
                    accessible_projects=None # Internal usage, bypass permission check logic or adjust
                )
                # 过滤只属于该用户的数据
                # get_performance_stats 返回的是整体数据，我们需要针对单个用户的
                # 这里 get_performance_stats 设计是给管理看板用的，不太适合个人周报
                # 我们需要一个更轻量的 get_user_weekly_stats
                
                # 重新计算个人数据以避免性能问题
                # 简单复用 stats 结构但只包含该用户
                user_stats = {
                   'overall_total': 0, 'overall_completed': 0, 'overall_overdue': 0, 'overall_rate': 0,
                   'project_stats': []
                }
                
                # ... (简化的统计逻辑，或者为了演示，暂时调用 send_weekly_digest_email(user, stats) 
                # 但 stats 必须是该用户的。
                # 由于 get_performance_stats 默认计算所有可访问项目，这对普通用户来说就是他们参与的项目。
                # 但对管理员来说是所有项目。
                # 为了准确性，我们应该模拟用户请求上下文，或者重构 stats 服务。
                
                # 暂时跳过复杂统计，只发送一封简单的确认邮件，或者仅当 stats 服务支持 user 参数时使用。
                # 假设 get_performance_stats 能够正确过滤（目前它基于 accessible_projects）
                # 我们需要为每个用户手动构建 accessible_projects
                from reports.utils import get_accessible_projects
                # 传入 user 对象给 get_accessible_projects
                user_projects = get_accessible_projects(user)
                
                # get_performance_stats 目前只接受 accessible_projects QuerySet
                # 它的逻辑是统计这些项目中的所有任务。对于普通用户，这就是他们参与的项目。
                # 但这会统计项目所有成员的数据。
                # 我们需要修改 get_performance_stats 或创建一个新的函数来只统计该用户的任务。
                # 由于这是修复任务，我们暂时使用 get_performance_stats 但需注意这可能是项目维度的周报，而不是个人维度的。
                # 更好的做法是过滤 Task.objects.filter(user=user)
                
                # 快速实现个人周报统计（替代 get_performance_stats）
                from tasks.models import Task
                from core.constants import TaskStatus
                from django.db.models import Q
                
                user_tasks = Task.objects.filter(user=user)
                total = user_tasks.count()
                completed = user_tasks.filter(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]).count()
                
                # 计算逾期：未完成且截止时间已过
                now = timezone.now()
                overdue = user_tasks.filter(
                    status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW],
                    due_at__lt=now
                ).count()
                
                rate = (completed / total * 100) if total else 0
                
                user_specific_stats = {
                    'overall_total': total,
                    'overall_completed': completed,
                    'overall_overdue': overdue,
                    'overall_rate': rate,
                    'project_stats': [] # 简化，不列出项目详情
                }
                
                send_weekly_digest_email(user, user_specific_stats)
                count += 1
            except Exception as e:
                print(f"Failed to process digest for {user.username}: {e}")

    return f"Sent {count} weekly digests."

@shared_task
def generate_export_file_task(job_id, export_type, params):
    """
    生成导出文件的异步任务。
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
            # 使用迭代器以避免内存问题，但我们需要为循环获取所有内容或小心处理迭代器
            # 由于这是后台任务，我们可以多花一点时间，但仍应保持内存效率。
            
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
        # 生成文件
        fd, path = tempfile.mkstemp(prefix=f'export_{job.export_type}_', suffix='.csv')
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([_sanitize_csv_cell(h) for h in header])
            
            total_processed = 0
            for row in rows_iterable:
                writer.writerow([_sanitize_csv_cell(col) for col in row])
                total_processed += 1
                if total_processed % 50 == 0:
                    job.progress = min(95, 5 + int((total_processed / (total_processed + 100)) * 90)) # Rough progress | 粗略进度
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
        # 重新引发以让 Celery 知道它失败了（可选，取决于我们是否想要重试）
        # raise e 
