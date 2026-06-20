from django.core.management.base import BaseCommand

from audit.services import archive_old_audit_logs


class Command(BaseCommand):
    help = "Archive old audit logs and optionally delete the hot-table rows."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=365, help='Archive logs older than N days.')
        parser.add_argument('--batch-size', type=int, default=1000, help='Rows processed per batch.')
        parser.add_argument(
            '--keep-hot',
            action='store_true',
            help='Archive matching rows without deleting them from AuditLog.',
        )

    def handle(self, *args, **options):
        result = archive_old_audit_logs(
            days=options['days'],
            batch_size=options['batch_size'],
            delete_after_archive=not options['keep_hot'],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Archived {result['archived']} audit logs; "
            f"deleted {result['deleted']} hot rows before {result['cutoff'].isoformat()}."
        ))
