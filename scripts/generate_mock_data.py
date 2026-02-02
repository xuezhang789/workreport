import os
import csv
import random
import faker
from datetime import datetime, timedelta, date
from tqdm import tqdm
import hashlib

# Configuration
NUM_USERS = 100_000
NUM_PROJECTS = 10_000
NUM_TASKS = 200_000
NUM_REPORTS = 10_000_000
# NUM_USERS = 100
# NUM_PROJECTS = 10
# NUM_TASKS = 200
# NUM_REPORTS = 1000
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'mock_data_output')
BATCH_SIZE = 10000

# Setup Faker
fake = faker.Faker('zh_CN')
Faker = faker.Faker

# Constants
ROLES = ['dev', 'qa', 'pm', 'ui', 'ops', 'mgr']
TASK_STATUSES = ['todo', 'in_progress', 'completed', 'blocked', 'closed'] # Based on typical flows
TASK_PRIORITIES = ['high', 'medium', 'low']
PROJECT_PHASES = ['Planning', 'Development', 'Testing', 'Deployment', 'Maintenance']

def get_hash(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()

class MockDataGenerator:
    def __init__(self):
        self.user_ids = []
        self.project_ids = []
        self.phase_ids = []
        self.task_ids = []
        
        # Pre-generate some static data to speed up
        self.common_sentences = [fake.sentence() for _ in range(1000)]
        self.common_words = [fake.word() for _ in range(1000)]

    def generate_users(self):
        print(f"Generating {NUM_USERS} users...")
        users_file = os.path.join(OUTPUT_DIR, 'users.csv')
        profiles_file = os.path.join(OUTPUT_DIR, 'profiles.csv')
        
        # Default password hash (e.g., pbkdf2 or just a placeholder for raw SQL)
        # For CSV import to Django, usually we use createsuperuser or set_password. 
        # Here we just put a dummy hash.
        dummy_password = "pbkdf2_sha256$260000$dummy$hash" 
        
        with open(users_file, 'w', newline='', encoding='utf-8') as fu, \
             open(profiles_file, 'w', newline='', encoding='utf-8') as fp:
            
            writer_u = csv.writer(fu)
            writer_p = csv.writer(fp)
            
            # Headers
            writer_u.writerow(['id', 'password', 'last_login', 'is_superuser', 'username', 'first_name', 'last_name', 'email', 'is_staff', 'is_active', 'date_joined'])
            writer_p.writerow(['id', 'user_id', 'position'])
            
            # Start from ID 2 (assuming 1 is admin)
            start_id = 2
            
            for i in tqdm(range(NUM_USERS)):
                uid = start_id + i
                username = f"user_{uid}"
                email = f"{username}@example.com"
                first_name = fake.first_name()
                last_name = fake.last_name()
                is_active = 1 if random.random() > 0.1 else 0
                date_joined = fake.date_time_between(start_date='-5y', end_date='now').strftime('%Y-%m-%d %H:%M:%S')
                
                writer_u.writerow([uid, dummy_password, '', 0, username, first_name, last_name, email, 0, is_active, date_joined])
                
                # Profile
                role = random.choice(ROLES)
                writer_p.writerow([i+1, uid, role]) # Profile ID starts at 1
                
                self.user_ids.append(uid)

    def generate_project_phases(self):
        # We need this for projects
        print("Generating project phases...")
        phases_file = os.path.join(OUTPUT_DIR, 'project_phases.csv')
        with open(phases_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'phase_name', 'progress_percentage', 'order_index', 'is_active'])
            
            for idx, name in enumerate(PROJECT_PHASES):
                pid = idx + 1
                pct = (idx + 1) * 20
                writer.writerow([pid, name, pct, idx, 1])
                self.phase_ids.append(pid)

    def generate_projects(self):
        print(f"Generating {NUM_PROJECTS} projects...")
        projects_file = os.path.join(OUTPUT_DIR, 'projects.csv')
        members_file = os.path.join(OUTPUT_DIR, 'project_members.csv')
        
        with open(projects_file, 'w', newline='', encoding='utf-8') as fp, \
             open(members_file, 'w', newline='', encoding='utf-8') as fm:
            
            writer_p = csv.writer(fp)
            writer_m = csv.writer(fm)
            
            # Project Header
            writer_p.writerow(['id', 'name', 'code', 'description', 'start_date', 'end_date', 'owner_id', 'is_active', 'current_phase_id', 'overall_progress', 'created_at'])
            # Member Header (M2M)
            writer_m.writerow(['id', 'project_id', 'user_id'])
            
            member_rel_id = 1
            
            for i in tqdm(range(NUM_PROJECTS)):
                pid = i + 1
                name = f"{fake.company_prefix()}项目-{fake.word()}"
                code = f"PROJ-{pid:05d}"
                desc = random.choice(self.common_sentences)
                start_date = fake.date_between(start_date='-3y', end_date='today')
                end_date = start_date + timedelta(days=random.randint(30, 365))
                owner_id = random.choice(self.user_ids)
                is_active = 1 if random.random() > 0.2 else 0
                phase_id = random.choice(self.phase_ids)
                progress = random.randint(0, 100)
                created_at = start_date.strftime('%Y-%m-%d %H:%M:%S')
                
                writer_p.writerow([pid, name, code, desc, start_date, end_date, owner_id, is_active, phase_id, progress, created_at])
                self.project_ids.append(pid)
                
                # Add Members (Random 2-10 members per project)
                num_members = random.randint(2, 10)
                members = random.sample(self.user_ids, num_members)
                if owner_id not in members:
                    members.append(owner_id)
                
                for mid in members:
                    writer_m.writerow([member_rel_id, pid, mid])
                    member_rel_id += 1

    def generate_tasks(self):
        print(f"Generating {NUM_TASKS} tasks...")
        tasks_file = os.path.join(OUTPUT_DIR, 'tasks.csv')
        
        with open(tasks_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'title', 'content', 'user_id', 'project_id', 'category', 'status', 'priority', 'due_at', 'created_at'])
            
            for i in tqdm(range(NUM_TASKS)):
                tid = i + 1
                title = random.choice(self.common_sentences)[:50]
                content = random.choice(self.common_sentences)
                project_id = random.choice(self.project_ids)
                # In real scenario, user should be member of project. 
                # For speed, we just pick random user or we could cache project members.
                # To be consistent with "Data Quality", let's just pick random user and assume they are added implicitly or just loose constraint.
                # Optimized: just pick random user.
                user_id = random.choice(self.user_ids)
                
                category = random.choice(['task', 'bug', 'feature'])
                status = random.choice(TASK_STATUSES)
                priority = random.choice(TASK_PRIORITIES)
                
                created_at = fake.date_time_between(start_date='-1y', end_date='now')
                due_at = created_at + timedelta(days=random.randint(1, 30))
                
                writer.writerow([tid, title, content, user_id, project_id, category, status, priority, due_at, created_at])
                self.task_ids.append(tid)

    def generate_reports(self):
        print(f"Generating {NUM_REPORTS} daily reports...")
        reports_file = os.path.join(OUTPUT_DIR, 'reports.csv')
        report_projects_file = os.path.join(OUTPUT_DIR, 'report_projects.csv')
        
        with open(reports_file, 'w', newline='', encoding='utf-8') as fr, \
             open(report_projects_file, 'w', newline='', encoding='utf-8') as frp:
            
            writer_r = csv.writer(fr)
            writer_rp = csv.writer(frp)
            
            writer_r.writerow(['id', 'user_id', 'date', 'role', 'status', 'today_work', 'tomorrow_plan', 'created_at'])
            writer_rp.writerow(['id', 'dailyreport_id', 'project_id'])
            
            rp_rel_id = 1
            
            # To generate 10M reports efficiently
            # We will just loop and generate random records.
            # Iterating 10M times in Python is slow. 
            # We can use bulk writing logic or just optimized loop.
            
            for i in tqdm(range(NUM_REPORTS)):
                rid = i + 1
                user_id = random.choice(self.user_ids)
                date_val = fake.date_between(start_date='-1y', end_date='today')
                role = random.choice(ROLES)
                status = 'submitted'
                
                # Use pre-generated text for speed
                work = random.choice(self.common_sentences)
                plan = random.choice(self.common_sentences)
                
                created_at = datetime.combine(date_val, datetime.min.time()) + timedelta(hours=20)
                
                writer_r.writerow([rid, user_id, date_val, role, status, work, plan, created_at])
                
                # Link to 1-3 projects
                num_projs = random.randint(1, 3)
                projs = random.sample(self.project_ids, num_projs)
                for pid in projs:
                    writer_rp.writerow([rp_rel_id, rid, pid])
                    rp_rel_id += 1

    def run(self):
        print("Starting Data Generation...")
        self.generate_users()
        self.generate_project_phases()
        self.generate_projects()
        self.generate_tasks()
        self.generate_reports()
        print(f"Data generation complete. Output in {OUTPUT_DIR}")

if __name__ == "__main__":
    generator = MockDataGenerator()
    generator.run()
