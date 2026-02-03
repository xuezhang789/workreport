import time
import statistics
import concurrent.futures
import sys
import os
import django

# Setup Django environment
sys.path.insert(0, '/Users/arlo/Downloads/workreport')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "workreport.settings")
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse

def run_benchmark():
    print("Starting Performance Benchmark...")
    
    # Setup Test User and Client
    User = get_user_model()
    # Create user if not exists
    username = 'bench_user'
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        user = User.objects.create_superuser(username, 'bench@example.com', 'password')
        
    client = Client()
    client.force_login(user)
    
    # Define targets
    # Ensure URL exists, otherwise fallback or error
    try:
        gantt_url = reverse('reports:api_advanced_gantt')
    except Exception as e:
        print(f"Error finding URL: {e}")
        return

    response_times = []
    errors = 0
    total_requests = 200
    concurrency = 10  # Simulating 10 concurrent users
    
    print(f"Target: {gantt_url}")
    print(f"Total Requests: {total_requests}")
    print(f"Concurrency: {concurrency}")
    
    def make_request(i):
        # Create a new client per thread to be safe, though Django Client is mostly stateless
        local_client = Client()
        local_client.force_login(user)
        
        start = time.time()
        try:
            # Randomize page to prevent pure database caching of the exact same query if any
            page = (i % 5) + 1 
            resp = local_client.get(gantt_url, {'page': page, 'limit': 20})
            if resp.status_code != 200:
                return None, False
            duration = (time.time() - start) * 1000 # ms
            return duration, True
        except Exception as e:
            return None, False

    start_total = time.time()
    
    # Use ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(make_request, range(total_requests)))
        
    end_total = time.time()
    
    for duration, success in results:
        if success and duration is not None:
            response_times.append(duration)
        else:
            errors += 1
            
    if not response_times:
        print("No successful requests.")
        return

    # Calculate stats
    avg_time = statistics.mean(response_times)
    p95_time = statistics.quantiles(response_times, n=20)[18] # 95th percentile
    p99_time = statistics.quantiles(response_times, n=100)[98] # 99th percentile
    max_time = max(response_times)
    min_time = min(response_times)
    
    print("\nBenchmark Results:")
    print(f"Total Duration: {end_total - start_total:.2f}s")
    print(f"Successful Requests: {len(response_times)}")
    print(f"Failed Requests: {errors}")
    print(f"Error Rate: {(errors/total_requests)*100:.2f}%")
    print("-" * 30)
    print(f"Average Response Time: {avg_time:.2f} ms")
    print(f"Min Response Time:     {min_time:.2f} ms")
    print(f"Max Response Time:     {max_time:.2f} ms")
    print(f"P95 Response Time:     {p95_time:.2f} ms")
    print(f"P99 Response Time:     {p99_time:.2f} ms")
    print("-" * 30)
    
    if p95_time < 300:
        print("✅ PASS: P95 < 300ms")
    else:
        print("❌ FAIL: P95 > 300ms")

if __name__ == "__main__":
    run_benchmark()
