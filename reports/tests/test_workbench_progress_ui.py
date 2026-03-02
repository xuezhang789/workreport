from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
import datetime
from projects.models import Project, ProjectPhaseConfig
from tasks.models import Task
from core.constants import TaskStatus

class WorkbenchProgressUITest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password')
        self.client = Client()
        self.client.force_login(self.user)
        
        self.phase = ProjectPhaseConfig.objects.create(phase_name="Dev", progress_percentage=0)
        self.project = Project.objects.create(
            name="Test Project", 
            code="TP", 
            owner=self.user, 
            current_phase=self.phase,
            is_active=True
        )
        
        # 1 DONE
        Task.objects.create(project=self.project, user=self.user, title="T1", status=TaskStatus.DONE)
        # 1 WIP
        Task.objects.create(project=self.project, user=self.user, title="T2", status=TaskStatus.IN_PROGRESS)
        # 1 TODO
        Task.objects.create(project=self.project, user=self.user, title="T3", status=TaskStatus.TODO)
        # 1 OVERDUE (TODO)
        Task.objects.create(
            project=self.project, 
            user=self.user, 
            title="T4", 
            status=TaskStatus.TODO,
            due_at=timezone.now() - datetime.timedelta(days=1)
        )

    def test_workbench_projects_display(self):
        url = reverse('reports:workbench_projects')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Verify Headers
        self.assertIn('PENDING', content)
        self.assertNotIn('WIP</th>', content)
        
        # Verify Data
        # Total 4, Done 1, Remaining 3 (1 WIP + 2 TODO)
        # Looking for Remaining count 3
        self.assertIn('>3</span>', content)
        
        # Verify Overdue Badge (1 overdue)
        self.assertIn('title="Overdue"', content)
        self.assertIn('>1!</span>', content)
