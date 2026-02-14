
import random
import os
import json
from datetime import timedelta, date, datetime
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction, connection
from django.utils import timezone
from faker import Faker
from core.models import Profile
from projects.models import (
    Project, ProjectPhaseConfig, 
    ProjectMemberPermission
)
from tasks.models import Task, TaskStatus
from work_logs.models import DailyReport

class Command(BaseCommand):
    help = 'Generates massive realistic Chinese test data: Users, Projects, Tasks, Reports'

    def add_arguments(self, parser):
        parser.add_argument('--users', type=int, default=1000, help='Number of users (default: 1000)')
        parser.add_argument('--projects', type=int, default=5000, help='Number of projects (default: 5000)')
        parser.add_argument('--tasks', type=int, default=100000, help='Number of tasks (default: 100000)')
        parser.add_argument('--reports', type=int, default=1000000, help='Number of daily reports (default: 1000000)')
        parser.add_argument('--clear', action='store_true', help='Clear existing data first')
        parser.add_argument('--export', type=str, help='Export data to JSON file path (e.g., data.json)')

    def handle(self, *args, **options):
        fake = Faker('zh_CN')
        num_users = options['users']
        num_projects = options['projects']
        num_tasks = options['tasks']
        num_reports = options['reports']
        
        # Performance tuning: bulk size
        BATCH_SIZE = 2000

        if options['clear']:
            self.stdout.write(self.style.WARNING('Clearing existing data...'))
            if connection.vendor == 'sqlite':
                with connection.cursor() as cursor:
                    cursor.execute('PRAGMA foreign_keys = OFF;')
            
            try:
                # Delete main objects (Cascades handles relations)
                Task.objects.all().delete()
                DailyReport.objects.all().delete()
                Project.objects.all().delete()
                User.objects.exclude(is_superuser=True).delete()
                self.stdout.write(self.style.SUCCESS('Data cleared.'))
            finally:
                if connection.vendor == 'sqlite':
                    with connection.cursor() as cursor:
                        cursor.execute('PRAGMA foreign_keys = ON;')

        # 1. Generate Users (Chinese Names)
        self.stdout.write(f'Generating {num_users} users...')
        users = []
        profiles = []
        existing_usernames = set(User.objects.values_list('username', flat=True))
        roles = [c[0] for c in Profile.ROLE_CHOICES]

        # Use bulk create for users
        for i in range(num_users):
            # Generate Chinese name
            full_name = fake.name()
            # Pinyin-like username
            from pypinyin import lazy_pinyin
            username = "".join(lazy_pinyin(full_name)) + f"_{random.randint(100, 999)}"
            
            if username in existing_usernames:
                username = f"{username}_{i}"
            existing_usernames.add(username)
            
            user = User(
                username=username,
                first_name=full_name[1:], # Given name
                last_name=full_name[0],   # Surname
                email=f"{username}@example.com",
                is_active=True
            )
            user.set_password('password123')
            users.append(user)
            
            if len(users) >= BATCH_SIZE:
                User.objects.bulk_create(users)
                # Fetch IDs for profiles
                created_users = User.objects.filter(username__in=[u.username for u in users])
                for u in created_users:
                    profiles.append(Profile(user=u, position=random.choice(roles)))
                users = []
                
        if users:
            User.objects.bulk_create(users)
            created_users = User.objects.filter(username__in=[u.username for u in users])
            for u in created_users:
                profiles.append(Profile(user=u, position=random.choice(roles)))
        
        if profiles:
            Profile.objects.bulk_create(profiles)
            
        self.stdout.write(self.style.SUCCESS(f'Created {num_users} users.'))
        
        # Cache all user IDs
        all_user_ids = list(User.objects.values_list('id', flat=True))
        if not all_user_ids:
            return

        # 2. Generate Projects (Industry Keywords)
        self.stdout.write(f'Generating {num_projects} projects...')
        
        # Project industries and types
        industries = ['金融', '电商', '医疗', '教育', '物流', '社交', '游戏', '人工智能', '大数据', '物联网']
        types = ['平台', '系统', 'APP', '小程序', '网站', '管理后台', '数据中台', '引擎', '接口服务']
        actions = ['开发', '重构', '升级', '维护', '迁移', '优化', '二期', '三期']
        
        projects = []
        phases = list(ProjectPhaseConfig.objects.all())
        if not phases:
            # Fallback
            from projects.management.commands.init_project_phases import Command as InitCmd
            InitCmd().handle()
            phases = list(ProjectPhaseConfig.objects.all())

        project_codes = set(Project.objects.values_list('code', flat=True))
        
        for i in range(num_projects):
            # Name: Industry + Type + Action
            p_name = f"{random.choice(industries)}{random.choice(types)}{random.choice(actions)}项目"
            
            # Ensure unique code
            while True:
                code = f"PRJ-{fake.unique.random_number(digits=6)}"
                if code not in project_codes:
                    project_codes.add(code)
                    break
            
            owner_id = random.choice(all_user_ids)
            phase = random.choice(phases)
            start_date = fake.date_between(start_date='-2y', end_date='today')
            end_date = start_date + timedelta(days=random.randint(30, 365))
            
            projects.append(Project(
                name=p_name,
                code=code,
                description=fake.paragraph(),
                owner_id=owner_id,
                current_phase=phase,
                overall_progress=phase.progress_percentage,
                start_date=start_date,
                end_date=end_date,
                is_active=True
            ))
            
            if len(projects) >= BATCH_SIZE:
                Project.objects.bulk_create(projects)
                projects = []
                self.stdout.write(f'  Projects: {i+1}/{num_projects}', ending='\r')
                
        if projects:
            Project.objects.bulk_create(projects)
            
        self.stdout.write(self.style.SUCCESS(f'\nCreated {num_projects} projects.'))

        # 2.1 Assign Members (Random distribution)
        self.stdout.write('Assigning project members...')
        all_project_ids = list(Project.objects.values_list('id', flat=True))
        ProjectMemberThrough = Project.members.through
        
        member_rels = []
        for pid in all_project_ids:
            # 5-20 members per project
            team_size = random.randint(5, 20)
            members = random.sample(all_user_ids, min(team_size, len(all_user_ids)))
            for uid in members:
                member_rels.append(ProjectMemberThrough(project_id=pid, user_id=uid))
            
            if len(member_rels) >= BATCH_SIZE * 5:
                ProjectMemberThrough.objects.bulk_create(member_rels, ignore_conflicts=True)
                member_rels = []
                
        if member_rels:
            ProjectMemberThrough.objects.bulk_create(member_rels, ignore_conflicts=True)
            
        self.stdout.write(self.style.SUCCESS('Members assigned.'))

        # 3. Generate Tasks (Associated with Project & User)
        self.stdout.write(f'Generating {num_tasks} tasks...')
        
        tasks = []
        tasks_created = 0
        
        # Iterate projects to ensure valid relations
        # We need ~20 tasks per project on average
        tasks_per_project = max(1, num_tasks // num_projects)
        
        # Load members map in chunks to save memory? 
        # For 5000 projects, we can load all.
        # Map: project_id -> [user_ids]
        members_map = {}
        # Fetch all relations
        all_rels = ProjectMemberThrough.objects.all().values('project_id', 'user_id')
        for r in all_rels:
            pid = r['project_id']
            if pid not in members_map:
                members_map[pid] = []
            members_map[pid].append(r['user_id'])
            
        for pid in all_project_ids:
            if tasks_created >= num_tasks:
                break
                
            p_members = members_map.get(pid, [])
            if not p_members:
                # Assign random if empty (fallback)
                p_members = [random.choice(all_user_ids)]
                
            # Randomize count slightly
            count = int(tasks_per_project * random.uniform(0.5, 1.5))
            
            for _ in range(count):
                if tasks_created >= num_tasks:
                    break
                    
                status = random.choice(['todo', 'in_progress', 'done', 'closed'])
                priority = random.choice(['low', 'medium', 'high'])
                created_at = fake.date_time_between(start_date='-1y', end_date='now', tzinfo=timezone.get_current_timezone())
                
                # Logic: Completed needs date
                completed_at = None
                if status in ['done', 'closed']:
                    completed_at = created_at + timedelta(days=random.randint(1, 10))
                    if completed_at > timezone.now(): completed_at = timezone.now()
                    
                # Logic: Due date after creation
                due_at = created_at + timedelta(days=random.randint(3, 14))
                
                tasks.append(Task(
                    title=f"{fake.word()}{fake.word()}功能{random.choice(['开发', '测试', '修复'])}",
                    content=fake.sentence(),
                    project_id=pid,
                    user_id=random.choice(p_members),
                    status=status,
                    priority=priority,
                    created_at=created_at,
                    completed_at=completed_at,
                    due_at=due_at
                ))
                tasks_created += 1
                
            if len(tasks) >= BATCH_SIZE:
                Task.objects.bulk_create(tasks)
                tasks = []
                self.stdout.write(f'  Tasks: {tasks_created}/{num_tasks}', ending='\r')
                
        if tasks:
            Task.objects.bulk_create(tasks)
            
        self.stdout.write(self.style.SUCCESS(f'\nCreated {tasks_created} tasks.'))

        # 4. Generate Daily Reports
        self.stdout.write(f'Generating {num_reports} reports...')
        
        # Strategy: Iterate users, generate history
        reports_created = 0
        reports = []
        report_proj_rels = []
        ReportProjectThrough = DailyReport.projects.through
        
        reports_per_user = max(1, num_reports // num_users)
        
        # User -> Projects map
        user_projects_map = {}
        for r in all_rels:
            uid = r['user_id']
            if uid not in user_projects_map:
                user_projects_map[uid] = []
            user_projects_map[uid].append(r['project_id'])
            
        for uid in all_user_ids:
            if reports_created >= num_reports:
                break
                
            my_projects = user_projects_map.get(uid, [])
            
            # Generate past X days
            start_date = date.today() - timedelta(days=reports_per_user)
            curr = start_date
            
            user_reports = []
            # Keep track of dates used for this user to avoid unique constraint violations
            # Since we iterate linearly, this shouldn't happen unless we loop back or have duplicate logic.
            # But just in case, or if running without clear:
            # We are running with --clear mostly, but let's be safe.
            # Actually, existing code iterates linearly.
            # The issue might be: reports_per_user is large, and we might hit same date if logic is flawed?
            # Or if we have multiple roles? The unique constraint includes role.
            # Let's fix role per report to be consistent or random but unique for date.
            # Usually a user has one report per day per role.
            # Let's pick ONE role for the user for all reports, or ensure (date, role) is unique.
            
            user_role = random.choice(roles) 
            
            while curr <= date.today():
                if reports_created >= num_reports:
                    break
                    
                # Skip weekends 30% chance
                if curr.weekday() >= 5 and random.random() > 0.7:
                    curr += timedelta(days=1)
                    continue
                    
                report = DailyReport(
                    user_id=uid,
                    date=curr,
                    role=user_role, # Use consistent role per user stream to avoid complexity
                    status='submitted',
                    today_work=f"1. {fake.sentence()}\n2. {fake.sentence()}",
                    progress_issues=fake.sentence() if random.random() > 0.8 else "无",
                    tomorrow_plan=f"1. {fake.sentence()}",
                    created_at=timezone.make_aware(datetime.combine(curr, datetime.min.time())) + timedelta(hours=18)
                )
                user_reports.append(report)
                reports_created += 1
                curr += timedelta(days=1)
                
            # Bulk create for user
            if user_reports:
                # Use ignore_conflicts=True to safely skip duplicates if any exist
                created = DailyReport.objects.bulk_create(user_reports, ignore_conflicts=True)
                
                # Assign projects to report
                # Note: with ignore_conflicts=True, 'created' might not contain all objects if DB doesn't support returning IDs on ignore
                # SQLite supports it on modern Django versions usually, but let's see.
                # If created is empty/partial, we might miss M2M. 
                # Better: ensure uniqueness in generation logic (done by linear date + fixed role)
                # And use standard bulk_create.
                
                for r in created:
                    if r.id is None: continue # Should not happen if inserted
                    if my_projects:
                        # Pick 1-2 random projects
                        picks = random.sample(my_projects, min(2, len(my_projects)))
                        for pid in picks:
                            report_proj_rels.append(ReportProjectThrough(dailyreport_id=r.id, project_id=pid))
                            
                if len(report_proj_rels) >= BATCH_SIZE * 5:
                    ReportProjectThrough.objects.bulk_create(report_proj_rels)
                    report_proj_rels = []
                    
                self.stdout.write(f'  Reports: {reports_created}/{num_reports}', ending='\r')

        if report_proj_rels:
            ReportProjectThrough.objects.bulk_create(report_proj_rels)
            
        self.stdout.write(self.style.SUCCESS(f'\nCreated {reports_created} reports.'))
        
        # 5. Export (Optional)
        if options['export']:
            self.stdout.write(f'Exporting to {options["export"]}...')
            
            # Helper for JSON serialization
            def json_default(obj):
                import decimal
                if isinstance(obj, decimal.Decimal):
                    return float(obj)
                if isinstance(obj, (date, datetime)):
                    return obj.isoformat()
                raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

            data = {
                'stats': {
                    'users': num_users,
                    'projects': num_projects,
                    'tasks': tasks_created,
                    'reports': reports_created
                },
                'sample_users': list(User.objects.values('username', 'first_name', 'last_name')[:10]),
                'sample_projects': list(Project.objects.values('name', 'code', 'overall_progress')[:10]),
            }
            with open(options['export'], 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=json_default)
            self.stdout.write(self.style.SUCCESS(f'Exported to {options["export"]}'))
