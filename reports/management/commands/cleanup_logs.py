from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from reports.models import AuditLog, Notification

class Command(BaseCommand):
    help = "Cleanup old audit logs and notifications to maintain database performance."

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Delete logs older than N days (default: 90)',
        )
        parser.add_argument(
            '--notification-days',
            type=int,
            default=30,
            help='Delete notifications older than N days (default: 30)',
        )

    def handle(self, *args, **options):
        days = options['days']
        notif_days = options['notification_days']
        
        # Cleanup Audit Logs
        cutoff = timezone.now() - timedelta(days=days)
        deleted_count, _ = AuditLog.objects.filter(created_at__lt=cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_count} audit logs older than {days} days."))
        
        # Cleanup Notifications
        notif_cutoff = timezone.now() - timedelta(days=notif_days)
        deleted_notif, _ = Notification.objects.filter(created_at__lt=notif_cutoff).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted_notif} notifications older than {notif_days} days."))
