
import os
import sys
import time
import django
from concurrent.futures import ThreadPoolExecutor
import statistics

# Setup Django environment
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "loadtest-secret-key")
os.environ.setdefault("DJANGO_ALLOWED_HOSTS", "testserver,127.0.0.1,localhost") # Allow testserver
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from tasks.models import Task
from projects.models import Project

def run_benchmark(url, user, concurrent_requests=10, total_requests=50):
    print(f"\nBenchmarking {url} with {concurrent_requests} concurrent threads, {total_requests} total requests...")
    
    times = []
    errors = 0
    
    def make_request():
        client = Client()
        client.force_login(user)
        start = time.time()
        response = client.get(url)
        duration = time.time() - start
        if response.status_code != 200:
            if errors == 0: # Print first error
                print(f"Request failed: {response.status_code}")
                # print(response.content[:200])
            return None, response.status_code
        return duration, 200

    with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
        futures = [executor.submit(make_request) for _ in range(total_requests)]
        for future in futures:
            duration, status = future.result()
            if duration is None:
                errors += 1
            else:
                times.append(duration)

    if not times:
        print("All requests failed!")
        return

    avg_time = statistics.mean(times)
    median_time = statistics.median(times)
    max_time = max(times)
    min_time = min(times)
    p95 = statistics.quantiles(times, n=20)[18] if len(times) >= 20 else max_time

    print(f"Results:")
    print(f"  Total Requests: {total_requests}")
    print(f"  Errors: {errors}")
    print(f"  Avg Time: {avg_time:.4f}s")
    print(f"  Median Time: {median_time:.4f}s")
    print(f"  P95 Time: {p95:.4f}s")
    print(f"  Min/Max: {min_time:.4f}s / {max_time:.4f}s")
    print(f"  Throughput: {len(times) / sum(times) * concurrent_requests:.2f} req/s (approx)")

def setup_data():
    User = get_user_model()
    admin, _ = User.objects.get_or_create(username='admin_loadtest')
    if not admin.check_password('pass'):
        admin.set_password('pass')
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        
    # Ensure we have some data
    project, _ = Project.objects.get_or_create(name='LoadTest Project', owner=admin)
    if Task.objects.count() < 100:
        print("Generating 100 dummy tasks...")
        tasks = [
            Task(title=f'Task {i}', project=project, user=admin, status='todo', priority='medium') 
            for i in range(100)
        ]
        Task.objects.bulk_create(tasks)
        
    return admin

if __name__ == "__main__":
    try:
        user = setup_data()
        
        # Test 1: Admin Task List (Critical Path)
        run_benchmark(reverse('tasks:admin_task_list'), user, concurrent_requests=5, total_requests=50)
        
        # Test 2: Project List (Permission Check Heavy)
        run_benchmark(reverse('projects:project_list'), user, concurrent_requests=5, total_requests=50)
        
    except Exception as e:
        print(f"Error: {e}")
