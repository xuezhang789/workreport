from django.core.management.base import BaseCommand
from reports.models import Task

class Command(BaseCommand):
    help = 'Migrates task statuses to the new scheme'

    def handle(self, *args, **options):
        # Map old -> new
        mapping = {
            'pending': 'todo',
            'on_hold': 'blocked',
            'completed': 'done',
            'overdue': 'todo', 
            'reopened': 'todo',
            'canceled': 'closed',
        }
        
        self.stdout.write("Starting status migration...")
        
        for old, new in mapping.items():
            count = Task.objects.filter(status=old).update(status=new)
            if count > 0:
                self.stdout.write(f"Updated {count} tasks from '{old}' to '{new}'")
            
        self.stdout.write(self.style.SUCCESS('Successfully migrated task statuses'))
