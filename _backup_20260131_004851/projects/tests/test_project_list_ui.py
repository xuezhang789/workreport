from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from projects.models import Project, ProjectPhaseConfig

class ProjectListUITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password', is_superuser=True)
        self.client = Client()
        self.client.login(username='testuser', password='password')
        
        self.phase = ProjectPhaseConfig.objects.create(phase_name="Development", progress_percentage=30)
        
        # Create projects that the user owns (so they are accessible)
        self.project1 = Project.objects.create(
            name="Alpha Project", 
            code="ALPHA", 
            owner=self.user,
            current_phase=self.phase,
            overall_progress=30.00,
            is_active=True
        )
        self.project2 = Project.objects.create(
            name="Beta Project", 
            code="BETA", 
            owner=self.user,
            current_phase=self.phase,
            overall_progress=50.00,
            is_active=True
        )

    def test_project_list_render(self):
        """Test that the project list page renders with correct context and UI elements."""
        url = reverse('projects:project_list')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'reports/project_list.html')
        
        # Check for projects in context
        self.assertContains(response, "Alpha Project")
        self.assertContains(response, "Beta Project")
        
        # Check for View Switcher Buttons
        self.assertContains(response, 'id="btnGrid"')
        self.assertContains(response, 'id="btnTable"')
        
        # Check for Table View Headers (hidden but present)
        self.assertContains(response, '项目名称 / Project Name')
        self.assertContains(response, '负责人 / Owner')
        self.assertContains(response, '阶段 / Phase')

    def test_project_search(self):
        """Test search functionality filters correctly."""
        url = reverse('projects:project_list')
        response = self.client.get(url, {'q': 'Alpha'})
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha Project")
        self.assertNotContains(response, "Beta Project")

    def test_project_table_row_rendering(self):
        """Test that table rows are rendered correctly."""
        url = reverse('projects:project_list')
        response = self.client.get(url)
        
        # Check for specific table cell content
        self.assertContains(response, 'class="table-progress-text"')
        self.assertContains(response, '30%') # Progress of Alpha
        self.assertContains(response, '50%') # Progress of Beta
        
        # Check for status indicator
        self.assertContains(response, 'status-active')

    def test_empty_state(self):
        """Test empty state when no projects match."""
        url = reverse('projects:project_list')
        response = self.client.get(url, {'q': 'NonExistent'})
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '没有找到相关项目')
        self.assertContains(response, 'No projects found')
