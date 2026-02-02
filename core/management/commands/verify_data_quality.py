from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from projects.models import Project
from tasks.models import Task
from work_logs.models import DailyReport

class Command(BaseCommand):
    help = 'Verifies data quality and consistency'

    def handle(self, *args, **options):
        self.stdout.write("Verifying data quality...")
        
        # 1. Check Users & Profiles
        users_count = User.objects.count()
        profiles_count = User.objects.filter(profile__isnull=False).count()
        self.stdout.write(f"Users: {users_count}")
        self.stdout.write(f"Profiles: {profiles_count}")
        if users_count != profiles_count:
            self.stdout.write(self.style.WARNING(f"Mismatch! {users_count - profiles_count} users missing profile."))
        
        # 2. Check Projects
        projects_count = Project.objects.count()
        self.stdout.write(f"Projects: {projects_count}")
        
        # 3. Check Tasks Consistency
        tasks_count = Task.objects.count()
        self.stdout.write(f"Tasks: {tasks_count}")
        
        # Verify Task User is Project Member
        invalid_tasks = 0
        # Checking all might be slow, check sample
        for task in Task.objects.all()[:1000]:
            if not task.project.members.filter(id=task.user_id).exists():
                invalid_tasks += 1
        
        if invalid_tasks > 0:
            self.stdout.write(self.style.ERROR(f"Found {invalid_tasks} tasks where user is NOT a project member (in sample of 1000)."))
        else:
            self.stdout.write(self.style.SUCCESS("Task consistency check passed (sample 1000)."))
            
        # 4. Check Reports
        reports_count = DailyReport.objects.count()
        self.stdout.write(f"Daily Reports: {reports_count}")
        
        # Verify Report Projects
        # Check if report.projects are actually related to user?
        # The constraint was "Daily report must link to user and project".
        
        self.stdout.write(self.style.SUCCESS("Data verification completed."))
