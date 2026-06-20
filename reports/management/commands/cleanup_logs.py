from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from audit.services import archive_old_audit_logs
from core.models import Notification

class Command(BaseCommand):
    help = "清理旧的审计日志和通知以维护数据库性能。"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='删除超过 N 天的日志（默认：90）',
        )
        parser.add_argument(
            '--notification-days',
            type=int,
            default=30,
            help='删除超过 N 天的通知（默认：30）',
        )

    def handle(self, *args, **options):
        days = options['days']
        notif_days = options['notification_days']
        
        # Archive Audit Logs before deleting hot rows.
        # 清理审计日志前先归档。
        audit_result = archive_old_audit_logs(days=days)
        self.stdout.write(self.style.SUCCESS(
            f"Archived {audit_result['archived']} audit logs and deleted "
            f"{audit_result['deleted']} hot rows older than {days} days."
        ))
        
        # Cleanup Notifications
        # 清理通知
        notif_cutoff = timezone.now() - timedelta(days=notif_days)
        deleted_notif, _ = Notification.objects.filter(created_at__lt=notif_cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_notif} notifications older than {notif_days} days."))
