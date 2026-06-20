
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from projects.models import Project, ProjectPhaseConfig, ProjectRepository

class ProjectDetailFixTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pm_user', password='password')
        self.client = Client()
        self.client.login(username='pm_user', password='password')
        
        self.phase1 = ProjectPhaseConfig.objects.create(phase_name="Phase 1", progress_percentage=10, order_index=1)
        self.phase2 = ProjectPhaseConfig.objects.create(phase_name="Phase 2", progress_percentage=50, order_index=2)
        
        self.project = Project.objects.create(
            name="Test Project", 
            code="TP-001", 
            owner=self.user,
            current_phase=self.phase1,
            overall_progress=10.00
        )

    def test_project_update_phase_view_success(self):
        url = reverse('projects:project_update_phase', args=[self.project.id])
        response = self.client.post(url, {'phase_id': self.phase2.id})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['progress'], 50)
        
        self.project.refresh_from_db()
        self.assertEqual(self.project.current_phase, self.phase2)
        self.assertEqual(self.project.overall_progress, 50.00)

    def test_project_update_phase_view_invalid_phase(self):
        url = reverse('projects:project_update_phase', args=[self.project.id])
        response = self.client.post(url, {'phase_id': 999})
        
        # View returns 404 JsonResponse for phase not found
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertEqual(data['status'], 'error')

    def test_project_update_phase_view_permission_denied(self):
        other_user = User.objects.create_user(username='other', password='password')
        self.client.login(username='other', password='password')
        
        url = reverse('projects:project_update_phase', args=[self.project.id])
        response = self.client.post(url, {'phase_id': self.phase2.id})
        
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data['status'], 'error')

    def test_project_detail_template_rendering(self):
        url = reverse('projects:project_detail', args=[self.project.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Phase & Progress')
        self.assertContains(response, 'update-phase-btn')

    def test_project_detail_repository_links_use_noopener(self):
        ProjectRepository.objects.create(
            project=self.project,
            name='Repo',
            url='https://example.com/repo',
        )

        response = self.client.get(reverse('projects:project_detail', args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rel="noopener"')

    def test_project_add_repository_rejects_invalid_url(self):
        response = self.client.post(
            reverse('projects:project_add_repository', args=[self.project.id]),
            {'name': 'Bad Repo', 'url': 'javascript:alert(1)'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['status'], 'error')
        self.assertFalse(ProjectRepository.objects.filter(project=self.project).exists())

    def test_project_add_repository_accepts_valid_url(self):
        response = self.client.post(
            reverse('projects:project_add_repository', args=[self.project.id]),
            {'name': 'Good Repo', 'url': 'https://example.com/repo.git'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertTrue(ProjectRepository.objects.filter(project=self.project).exists())
