import random
from datetime import timedelta, date
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction, connection
from django.utils import timezone
from faker import Faker
from core.models import Profile
from projects.models import (
    Project, ProjectPhaseConfig, ProjectPhaseChangeLog, 
    ProjectAttachment, ProjectMemberPermission
)
from tasks.models import (
    Task, TaskComment, TaskAttachment, 
    TaskSlaTimer, TaskTemplateVersion
)
from work_logs.models import DailyReport, ReminderRule, ReportMiss, ReportTemplateVersion
from audit.models import AuditLog, TaskHistory

class Command(BaseCommand):
    help = 'Generates large scale test data for performance testing'

    def add_arguments(self, parser):
        parser.add_argument('--users', type=int, default=500, help='Number of users to create')
        parser.add_argument('--projects', type=int, default=10000, help='Number of projects to create')
        parser.add_argument('--tasks', type=int, default=100000, help='Number of tasks to create')
        parser.add_argument('--reports', type=int, default=1000000, help='Number of daily reports to create')
        parser.add_argument('--clear', action='store_true', help='Clear existing data first')

    def handle(self, *args, **options):
        fake = Faker('zh_CN')
        num_users = options['users']
        num_projects = options['projects']
        num_tasks = options['tasks']
        num_reports = options['reports']

        if options['clear']:
            self.stdout.write(self.style.WARNING('Clearing existing data...'))
            
            # Disable FK checks for SQLite to prevent IntegrityError during massive delete
            # This is safe because we are clearing everything related anyway.
            if connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute('PRAGMA foreign_keys = OFF;')

            try:
                # Simplify deletion - let Django cascade handle it
                # Delete dependent models that might not cascade or are independent
                AuditLog.objects.all().delete()
                
                # Delete Projects (Cascades to Tasks, Attachments, Logs, ReminderRules, etc.)
                Project.objects.all().delete()
                
                # Delete Users (Cascades to DailyReports, Profiles, UserRoles, etc.)
                User.objects.exclude(is_superuser=True).delete()
                
                # Cleanup any orphans if necessary (e.g. independent templates)
                ReportTemplateVersion.objects.all().delete()
                
                self.stdout.write(self.style.SUCCESS('Data cleared.'))
            finally:
                if connection.vendor == 'sqlite':
                    with connection.cursor() as cursor:
                        cursor.execute('PRAGMA foreign_keys = ON;')
            
            # Verify cleanup
            report_count = DailyReport.objects.count()
            if report_count > 0:
                self.stdout.write(self.style.ERROR(f"Failed to clear DailyReport! Count: {report_count}"))
                DailyReport.objects.all().delete()

        # 1. Generate Users
        self.stdout.write(f'Generating {num_users} users...')
        users = []
        profiles = []
        
        # Pre-fetch existing usernames to avoid collision if not cleared
        existing_usernames = set(User.objects.values_list('username', flat=True))
        
        roles = [c[0] for c in Profile.ROLE_CHOICES]
        
        batch_size = 1000
        
        for i in range(num_users):
            username = fake.user_name()
            while username in existing_usernames:
                username = f"{fake.user_name()}_{random.randint(1000, 9999)}"
            existing_usernames.add(username)
            
            user = User(
                username=username,
                email=fake.email(),
                first_name=fake.last_name(),
                last_name=fake.first_name(),
                is_active=True
            )
            user.set_password('password123')
            users.append(user)
            
            if len(users) >= batch_size:
                User.objects.bulk_create(users)
                # We need to fetch them back to get IDs for Profiles
                created_users = User.objects.filter(username__in=[u.username for u in users])
                for u in created_users:
                    profiles.append(Profile(user=u, position=random.choice(roles)))
                users = []
                
        if users:
            User.objects.bulk_create(users)
            created_users = User.objects.filter(username__in=[u.username for u in users])
            for u in created_users:
                profiles.append(Profile(user=u, position=random.choice(roles)))
        
        Profile.objects.bulk_create(profiles)
        self.stdout.write(self.style.SUCCESS(f'Created {num_users} users.'))

        # Reload all users IDs for relationship generation
        all_user_ids = list(User.objects.values_list('id', flat=True))
        if not all_user_ids:
            self.stdout.write(self.style.ERROR("No users found! Aborting."))
            return

        # 2. Generate Projects
        self.stdout.write(f'Generating {num_projects} projects...')
        projects = []
        phases = list(ProjectPhaseConfig.objects.all())
        if not phases:
            # Create default phases if missing
            phases = [
                ProjectPhaseConfig.objects.create(phase_name="规划中", progress_percentage=0, order_index=1),
                ProjectPhaseConfig.objects.create(phase_name="进行中", progress_percentage=50, order_index=2),
                ProjectPhaseConfig.objects.create(phase_name="已完成", progress_percentage=100, order_index=3),
            ]

        project_codes = set(Project.objects.values_list('code', flat=True))
        
        for i in range(num_projects):
            code = fake.unique.bothify(text='PROJ-#####')
            while code in project_codes:
                code = fake.unique.bothify(text='PROJ-#####')
            project_codes.add(code)
            
            owner_id = random.choice(all_user_ids)
            phase = random.choice(phases)
            
            # Start date within last 2 years
            start_date = fake.date_between(start_date='-2y', end_date='today')
            end_date = start_date + timedelta(days=random.randint(30, 365))
            
            projects.append(Project(
                name=f"{fake.city_suffix()}{fake.word()}项目",
                code=code,
                description=fake.text(max_nb_chars=100),
                start_date=start_date,
                end_date=end_date,
                owner_id=owner_id,
                current_phase=phase,
                overall_progress=phase.progress_percentage,
                is_active=True
            ))
            
            if len(projects) >= batch_size:
                Project.objects.bulk_create(projects)
                projects = []
                self.stdout.write(f'  Projects: {i+1}/{num_projects}', ending='\r')
                
        if projects:
            Project.objects.bulk_create(projects)
        self.stdout.write(self.style.SUCCESS(f'\nCreated {num_projects} projects.'))

        # 2.1 Assign Project Members (M2M)
        self.stdout.write('Assigning project members...')
        all_project_ids = list(Project.objects.values_list('id', flat=True))
        
        # Bulk create M2M relations using through model
        ProjectMemberThrough = Project.members.through
        ProjectManagerThrough = Project.managers.through
        
        member_relations = []
        manager_relations = []
        
        # We need to map project to its members for Task generation later
        # To avoid massive memory usage, we'll process in chunks or generate deterministically
        # For simplicity and speed, let's just generate random relations now
        # But for Task consistency, we need to know who is in what project.
        # Strategy: Iterate projects, pick random users, create relations.
        
        # To optimize, we'll do this in batches of projects
        
        # Store project->members map for a subset of projects to generate tasks immediately?
        # No, let's just populate DB first. For tasks, we'll query DB or assume probability.
        # Actually, for "Task owner must be project member", we MUST query.
        
        total_rels = 0
        for pid in all_project_ids:
            # Randomly 5-15 members per project
            team_size = random.randint(5, 15)
            team_ids = random.sample(all_user_ids, min(team_size, len(all_user_ids)))
            
            for uid in team_ids:
                member_relations.append(ProjectMemberThrough(project_id=pid, user_id=uid))
            
            # Randomly 1-2 managers
            manager_ids = random.sample(team_ids, min(2, len(team_ids)))
            for uid in manager_ids:
                manager_relations.append(ProjectManagerThrough(project_id=pid, user_id=uid))
                
            if len(member_relations) >= 5000:
                ProjectMemberThrough.objects.bulk_create(member_relations, ignore_conflicts=True)
                ProjectManagerThrough.objects.bulk_create(manager_relations, ignore_conflicts=True)
                member_relations = []
                manager_relations = []
                self.stdout.write(f'  Processed members for project {pid}...', ending='\r')
                
        if member_relations:
            ProjectMemberThrough.objects.bulk_create(member_relations, ignore_conflicts=True)
            ProjectManagerThrough.objects.bulk_create(manager_relations, ignore_conflicts=True)
            
        self.stdout.write(self.style.SUCCESS('\nProject members assigned.'))

        # 3. Generate Tasks
        self.stdout.write(f'Generating {num_tasks} tasks...')
        tasks = []
        
        # To ensure consistency (Task User in Project), we iterate projects
        # We need ~10 tasks per project on average (100k tasks / 10k projects)
        
        # Fetch project members efficiently?
        # Iterating 10k projects is fine.
        
        tasks_created = 0
        
        # We'll process projects in chunks to keep memory low
        chunk_size = 100
        for i in range(0, len(all_project_ids), chunk_size):
            chunk_pids = all_project_ids[i:i+chunk_size]
            
            # Fetch members for this chunk
            # Map: project_id -> list of user_ids
            members_map = {}
            relations = ProjectMemberThrough.objects.filter(project_id__in=chunk_pids)
            for r in relations:
                if r.project_id not in members_map:
                    members_map[r.project_id] = []
                members_map[r.project_id].append(r.user_id)
            
            for pid in chunk_pids:
                project_members = members_map.get(pid, [])
                if not project_members:
                    # Fallback: assign to random user (and maybe add them to project? or just skip)
                    # Requirement says "Task owner must be project member".
                    # If no members (unlikely due to step 2.1), pick random user and add them.
                    fallback_user = random.choice(all_user_ids)
                    ProjectMemberThrough.objects.create(project_id=pid, user_id=fallback_user)
                    project_members = [fallback_user]
                
                # Generate ~10 tasks
                num_tasks_for_proj = random.randint(5, 15)
                for _ in range(num_tasks_for_proj):
                    if tasks_created >= num_tasks:
                        break
                        
                    status = random.choice(['todo', 'in_progress', 'in_review', 'done', 'closed'])
                    created_at = fake.date_time_between(start_date='-1y', end_date='now', tzinfo=timezone.get_current_timezone())
                    
                    completed_at = None
                    if status in ['done', 'closed']:
                        completed_at = created_at + timedelta(days=random.randint(1, 30))
                        if completed_at > timezone.now():
                            completed_at = timezone.now()
                            
                    tasks.append(Task(
                        title=fake.sentence(nb_words=6),
                        content=fake.paragraph(),
                        project_id=pid,
                        user_id=random.choice(project_members),
                        status=status,
                        priority=random.choice(['low', 'medium', 'high']),
                        created_at=created_at,
                        completed_at=completed_at,
                        due_at=created_at + timedelta(days=random.randint(2, 14))
                    ))
                    tasks_created += 1
            
            if len(tasks) >= 5000:
                Task.objects.bulk_create(tasks)
                tasks = []
                self.stdout.write(f'  Tasks: {tasks_created}/{num_tasks}', ending='\r')
                
            if tasks_created >= num_tasks:
                break
                
        if tasks:
            Task.objects.bulk_create(tasks)
        self.stdout.write(self.style.SUCCESS(f'\nCreated {tasks_created} tasks.'))

        # 4. Generate Daily Reports
        self.stdout.write(f'Generating {num_reports} daily reports...')
        
        # 1M reports / 500 users = 2000 reports per user.
        # We iterate users and generate reports for past dates.
        
        # Report - Project M2M relation needs to be consistent (User in Project)
        # So for each user, we need to know which projects they are in.
        
        reports = []
        report_project_relations = []
        ReportProjectThrough = DailyReport.projects.through
        
        reports_created = 0
        
        # Process users in chunks
        for i in range(0, len(all_user_ids), chunk_size):
            chunk_uids = all_user_ids[i:i+chunk_size]
            
            # Check for duplicate users in chunk? No, list slice is safe.
            
            # Fetch user projects
            user_projects_map = {}
            rels = ProjectMemberThrough.objects.filter(user_id__in=chunk_uids)
            for r in rels:
                if r.user_id not in user_projects_map:
                    user_projects_map[r.user_id] = []
                user_projects_map[r.user_id].append(r.project_id)
                
            for uid in chunk_uids:
                my_projects = user_projects_map.get(uid, [])
                if not my_projects:
                    continue # Skip user if no projects
                
                # Generate reports for the last X days
                # To reach 1M total, we need roughly num_reports / num_users per user
                if len(all_user_ids) > 0:
                    target_per_user = int(num_reports / len(all_user_ids)) * 2 # x2 buffer
                else:
                    target_per_user = 10
                
                # Cap target days to reasonable history (e.g. 5 years)
                target_per_user = min(target_per_user, 365*5)
                
                start_date = date.today() - timedelta(days=target_per_user)
                
                current_date = start_date
                
                # Track dates for this user to ensure uniqueness locally
                generated_dates = set()

                while current_date <= date.today():
                    if reports_created >= num_reports:
                        break
                        
                    # Skip weekends randomly (80% workdays)
                    if current_date.weekday() >= 5 and random.random() > 0.1:
                        current_date += timedelta(days=1)
                        continue
                    
                    if current_date in generated_dates:
                         current_date += timedelta(days=1)
                         continue
                    generated_dates.add(current_date)

                    report = DailyReport(
                        user_id=uid,
                        date=current_date,
                        role=random.choice(roles),
                        status='submitted',
                        today_work=fake.paragraph(),
                        progress_issues=fake.sentence(),
                        tomorrow_plan=fake.sentence(),
                        project=f"Project count: {len(my_projects)}" # Legacy field
                    )
                    reports.append(report)
                    
                    # We need to save report to get ID for M2M, BUT bulk_create on Postgres/SQLite returns IDs (Django 4.x+ does)
                    # Assuming modern Django.
                    
                    current_date += timedelta(days=1)
                    reports_created += 1
            
            # Bulk create reports for this chunk of users
            if reports:
                created_reports = DailyReport.objects.bulk_create(reports)
                
                # Create M2M relations for these reports
                # Randomly assign 1-3 of user's projects to the report
                for r in created_reports:
                    u_projs = user_projects_map.get(r.user_id, [])
                    if u_projs:
                        selected_projs = random.sample(u_projs, min(random.randint(1, 3), len(u_projs)))
                        for pid in selected_projs:
                            report_project_relations.append(ReportProjectThrough(dailyreport_id=r.id, project_id=pid))
                
                ReportProjectThrough.objects.bulk_create(report_project_relations)
                
                reports = []
                report_project_relations = []
                self.stdout.write(f'  Reports: {reports_created}/{num_reports}', ending='\r')
                
            if reports_created >= num_reports:
                break
                
        self.stdout.write(self.style.SUCCESS(f'\nCreated {reports_created} daily reports.'))
        self.stdout.write(self.style.SUCCESS('Data generation completed successfully!'))
