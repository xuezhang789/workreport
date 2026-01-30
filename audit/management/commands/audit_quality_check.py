
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from audit.models import AuditLog
from django.db import transaction

class Command(BaseCommand):
    help = 'Audit data quality check: Identifies and fixes duplicates and errors in Audit Logs.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Actually delete duplicates and fix errors.',
        )

    def handle(self, *args, **options):
        fix = options['fix']
        self.stdout.write("Starting Audit Log Quality Check...")
        
        # 1. Check for Duplicates
        # Definition: Same user, target, action, and details within 5 seconds.
        
        logs = AuditLog.objects.all().order_by('created_at')
        duplicates = []
        
        # We need to compare with "previous" log
        # To avoid loading all into memory, we can use iterator, but need to track potential duplicates window.
        # Since strict order is by created_at, duplicates should be adjacent or close.
        
        prev_log = None
        window = timedelta(seconds=5)
        
        # Group duplicates to keep only one (the first one)
        to_delete_ids = []
        
        total_checked = 0
        dup_count = 0
        
        # Iterate efficiently
        # Note: If volume is huge, we might need more sophisticated query, but for now iterator is fine.
        for log in logs.iterator(chunk_size=1000):
            total_checked += 1
            if prev_log:
                # Check condition
                time_diff = log.created_at - prev_log.created_at
                
                if (time_diff < window and
                    log.user_id == prev_log.user_id and
                    log.target_type == prev_log.target_type and
                    log.target_id == prev_log.target_id and
                    log.action == prev_log.action and
                    log.details == prev_log.details):
                    
                    # Found duplicate
                    dup_count += 1
                    duplicates.append(f"Duplicate: {log} (Original: {prev_log.id})")
                    to_delete_ids.append(log.id)
                    # Don't update prev_log, so subsequent duplicates also match the first one (original)
                    continue
            
            prev_log = log

        self.stdout.write(f"Checked {total_checked} logs.")
        self.stdout.write(f"Found {dup_count} duplicate records.")
        
        # 2. Check for Empty Updates (Data Integrity)
        # Action 'update' but details['diff'] is empty
        empty_updates = []
        empty_update_ids = []
        
        for log in AuditLog.objects.filter(action='update'):
            if not log.details or 'diff' not in log.details or not log.details['diff']:
                empty_updates.append(f"Empty Update: {log.id}")
                empty_update_ids.append(log.id)
                
        self.stdout.write(f"Found {len(empty_updates)} empty update records.")

        if fix:
            with transaction.atomic():
                if to_delete_ids:
                    cnt, _ = AuditLog.objects.filter(id__in=to_delete_ids).delete()
                    self.stdout.write(self.style.SUCCESS(f"Deleted {cnt} duplicate logs."))
                
                if empty_update_ids:
                    cnt, _ = AuditLog.objects.filter(id__in=empty_update_ids).delete()
                    self.stdout.write(self.style.SUCCESS(f"Deleted {cnt} empty update logs."))
        else:
            if to_delete_ids or empty_update_ids:
                self.stdout.write(self.style.WARNING("Run with --fix to apply changes."))
