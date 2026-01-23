import random
import string
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from reports.models import Project, Task, DailyReport, Profile

class Command(BaseCommand):
    help = 'Generate massive test data: 1000 Users, 200 Projects, 2000 Tasks, 10000 Reports'

    def handle(self, *args, **kwargs):
        self.stdout.write('Starting data generation...')
        
        # Prepare password hash once
        default_password = make_password('password123')
        
        # 1. Users
        self.stdout.write('Generating 1000 Users...')
        users_to_create = []
        existing_users_count = User.objects.count()
        
        # Generate batch of users
        for i in range(1000):
            username = f'user_{existing_users_count + i}_{self._random_string(5)}'
            users_to_create.append(User(
                username=username, 
                email=f'{username}@example.com', 
                password=default_password,
                is_active=True,
                is_staff=False,
                is_superuser=False
            ))
        
        User.objects.bulk_create(users_to_create)
        # Re-fetch created users to get their IDs
        # Assuming ID is auto-increment, we can fetch the last 1000
        created_users = list(User.objects.order_by('-id')[:1000])
        
        # 2. Profiles
        self.stdout.write('Generating Profiles...')
        profiles_to_create = []
        roles = [c[0] for c in Profile.ROLE_CHOICES]
        for user in created_users:
            profiles_to_create.append(Profile(user=user, position=random.choice(roles)))
        Profile.objects.bulk_create(profiles_to_create)

        # 3. Projects
        self.stdout.write('Generating 200 Projects...')
        projects_to_create = []
        existing_projects_count = Project.objects.count()
        for i in range(200):
            code = f'PRJ_{existing_projects_count + i}_{self._random_string(3)}'.upper()
            projects_to_create.append(Project(
                name=f'Project {code}',
                code=code,
                description='Auto generated project description.',
                owner=random.choice(created_users),
                is_active=True,
                start_date=timezone.now().date(),
                end_date=timezone.now().date() + timedelta(days=90)
            ))
        Project.objects.bulk_create(projects_to_create)
        created_projects = list(Project.objects.order_by('-id')[:200])

        # 4. Project Members (M2M)
        self.stdout.write('Associating Members to Projects...')
        ProjectMember = Project.members.through
        m2m_relations = []
        for project in created_projects:
            # Randomly assign 5-20 members per project
            members = random.sample(created_users, k=random.randint(5, 20))
            for member in members:
                m2m_relations.append(ProjectMember(project_id=project.id, user_id=member.id))
        
        ProjectMember.objects.bulk_create(m2m_relations, ignore_conflicts=True)

        # 5. Tasks
        self.stdout.write('Generating 2000 Tasks...')
        tasks_to_create = []
        statuses = [c[0] for c in Task.STATUS_CHOICES]
        for i in range(2000):
            project = random.choice(created_projects)
            user = random.choice(created_users)
            
            created_date = timezone.now() - timedelta(days=random.randint(0, 30))
            due_date = created_date + timedelta(days=random.randint(1, 14))
            
            tasks_to_create.append(Task(
                title=f'Task {i} {self._random_string(8)}',
                content='Auto generated task content.',
                user=user,
                project=project,
                status=random.choice(statuses),
                created_at=created_date,
                due_at=due_date
            ))
        Task.objects.bulk_create(tasks_to_create)

        # 6. Daily Reports
        self.stdout.write('Generating 10000 Daily Reports...')
        reports_to_create = []
        report_roles = [c[0] for c in DailyReport.ROLE_CHOICES]
        
        # Use a set to track (user, date, role) to avoid unique constraint errors before bulk_create
        seen_reports = set()
        
        count = 0
        while count < 10000:
            user = random.choice(created_users)
            date = timezone.now().date() - timedelta(days=random.randint(0, 60))
            role = random.choice(report_roles)
            
            key = (user.id, date, role)
            if key in seen_reports:
                continue
            seen_reports.add(key)
            
            reports_to_create.append(DailyReport(
                user=user,
                date=date,
                role=role,
                today_work=f'Completed work item {self._random_string(10)}\n- Subtask A\n- Subtask B',
                tomorrow_plan=f'Plan to do {self._random_string(10)}',
                progress_issues='None',
                status='submitted'
            ))
            count += 1
        
        DailyReport.objects.bulk_create(reports_to_create, ignore_conflicts=True)
        
        # Associate projects to reports
        self.stdout.write('Associating Projects to Reports...')
        # We need report IDs, so fetch them
        new_reports = DailyReport.objects.order_by('-id')[:10000]
        ReportProject = DailyReport.projects.through
        rp_relations = []
        for report in new_reports:
             projs = random.sample(created_projects, k=random.randint(1, 3))
             for p in projs:
                 rp_relations.append(ReportProject(dailyreport_id=report.id, project_id=p.id))
        
        ReportProject.objects.bulk_create(rp_relations, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS(f'Successfully generated:\n- 1000 Users (password: password123)\n- 200 Projects\n- 2000 Tasks\n- 10000 Reports'))

    def _random_string(self, length):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
