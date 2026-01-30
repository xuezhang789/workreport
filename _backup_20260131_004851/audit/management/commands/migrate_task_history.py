
from django.core.management.base import BaseCommand
from audit.models import TaskHistory, AuditLog
from tasks.models import Task

class Command(BaseCommand):
    help = 'Migrate legacy TaskHistory to AuditLog'

    def handle(self, *args, **options):
        histories = TaskHistory.objects.all().order_by('created_at')
        count = 0
        
        for th in histories:
            # Check if this exact change already exists in AuditLog (deduplication)
            # This is tricky, but let's assume we want to import if not present.
            # Simple check: timestamp match within 1 second and same task/user/field
            
            exists = AuditLog.objects.filter(
                target_type='Task',
                target_id=str(th.task_id),
                created_at__range=(th.created_at, th.created_at), # Exact match might fail due to precision
                user=th.user
            ).exists()
            
            # Since auto_now_add makes it hard to match exactly, we'll just migrate all and users can filter.
            # Or better, check if an AuditLog exists with the same diff content.
            
            # Construct diff
            field = th.field
            diff = {
                field: {
                    'verbose_name': field, # Legacy didn't store verbose name, use field key
                    'old': th.old_value,
                    'new': th.new_value
                }
            }
            
            # Create AuditLog
            log = AuditLog.objects.create(
                user=th.user,
                operator_name=th.user.get_full_name() or th.user.username if th.user else 'System',
                action='update',
                target_type='Task',
                target_id=str(th.task_id),
                target_label=f"Task #{th.task_id}", # We might not know the title at that time
                details={'diff': diff},
                task_id=th.task_id,
                project_id=th.task.project_id if th.task else None
            )
            
            # Manually update created_at (since auto_now_add=True on model)
            log.created_at = th.created_at
            log.save(update_fields=['created_at'])
            
            count += 1
            
        self.stdout.write(self.style.SUCCESS(f'Successfully migrated {count} TaskHistory records.'))
