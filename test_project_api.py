
import os
import sys
import django
import json
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory

# Setup Django
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
os.environ.setdefault('DJANGO_SECRET_KEY', 'dummy')
os.environ.setdefault('DEBUG', 'True')
django.setup()

from projects.views import project_search_api
from projects.models import Project

User = get_user_model()

def test_api():
    # Find a user with projects
    # From previous diagnosis: user_55257 has 2 projects
    try:
        user = User.objects.get(id=55257)
    except User.DoesNotExist:
        user = User.objects.first()
        print(f"User 55257 not found, using {user.username}")

    print(f"Testing API for user: {user.username} (ID: {user.id})")
    
    factory = RequestFactory()
    request = factory.get('/projects/api/search/', {'mode': 'lite', 'limit': 5000})
    request.user = user
    
    # Mock session
    class MockSession(dict):
        def save(self): pass
        def get(self, k, d=None): return super().get(k, d)
        
    request.session = MockSession()
    
    response = project_search_api(request)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        content = json.loads(response.content)
        results = content.get('results', [])
        print(f"Results Count: {len(results)}")
        for p in results[:5]:
            print(f" - {p['name']} (ID: {p['id']}, Status: {p['status']})")
    else:
        print(response.content)

if __name__ == '__main__':
    test_api()
