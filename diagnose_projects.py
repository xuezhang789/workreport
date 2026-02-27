
import os
import sys
import django
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q

# Setup Django
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
os.environ.setdefault('DJANGO_SECRET_KEY', 'django-insecure-dummy-key-for-diagnosis')
os.environ.setdefault('DEBUG', 'True')
django.setup()

from projects.models import Project
from reports.utils import get_accessible_projects

User = get_user_model()

def diagnose():
    print("--- Project Access Diagnosis v2 ---")
    
    # Try finding the user from previous failure
    try:
        user = User.objects.get(id=55257) # A user with projects
    except User.DoesNotExist:
        user = User.objects.first()
        
    if not user:
        print("No users found.")
        return

    print(f"Diagnosing User: {user.username} (ID: {user.id})")
    print(f"Is Active: {user.is_active}")
    print(f"Is Superuser: {user.is_superuser}")
    
    # 1. Direct Ownership
    owned = Project.objects.filter(owner=user)
    print(f"  Owned Projects: {owned.count()}")
    for p in owned:
        print(f"    - {p.name} (ID: {p.id}, Active: {p.is_active})")
        
    # 2. Members
    member_of = Project.objects.filter(members=user)
    print(f"  Member of Projects: {member_of.count()}")
    for p in member_of:
        print(f"    - {p.name} (ID: {p.id}, Active: {p.is_active})")
        
    # 3. get_accessible_projects()
    accessible = get_accessible_projects(user)
    print(f"  get_accessible_projects() count: {accessible.count()}")
    for p in accessible:
        print(f"    - {p.name} (ID: {p.id}, Active: {p.is_active})")
        
    # 4. Simulate View Logic
    project_filter = Q(is_active=True)
    accessible_ids = get_accessible_projects(user).values_list('id', flat=True)
    project_filter &= Q(id__in=accessible_ids)
    
    qs = Project.objects.filter(project_filter)
    print(f"  View QuerySet Count: {qs.count()}")
    
    # 5. Check Cache Content
    from django.core.cache import cache
    cache_key = f"accessible_projects_ids:{user.id}"
    cached_val = cache.get(cache_key)
    print(f"  Cache Key '{cache_key}': {cached_val}")
    
    # 6. Check for inactive projects that SHOULD be visible if active
    inactive_owned = Project.objects.filter(owner=user, is_active=False)
    print(f"  Inactive Owned: {inactive_owned.count()}")

if __name__ == '__main__':
    diagnose()
