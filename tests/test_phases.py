from django.test import TestCase, Client
from django.contrib.auth.models import User
from reports.models import Project, ProjectPhaseConfig, ProjectPhaseChangeLog
from projects.views import _send_phase_change_notification
from django.core import mail

class PhaseManagementTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.user = User.objects.create_user('user', 'user@example.com', 'password')
        self.client.force_login(self.admin)
        
        # Create initial phases (already done by migration/seed, but let's ensure for test isolation)
        self.phase1 = ProjectPhaseConfig.objects.create(phase_name='Phase 1', progress_percentage=10, order_index=1)
        self.phase2 = ProjectPhaseConfig.objects.create(phase_name='Phase 2', progress_percentage=50, order_index=2)
        
        self.project = Project.objects.create(
            name='Test Project',
            code='TP-001',
            owner=self.user,
            current_phase=self.phase1,
            overall_progress=10
        )

    def test_phase_config_crud(self):
        # List
        response = self.client.get('/projects/phases/')
        self.assertEqual(response.status_code, 200)
        
        # Create
        response = self.client.post('/projects/phases/new/', {
            'phase_name': 'New Phase',
            'progress_percentage': 99,
            'order_index': 10,
            'is_active': True
        })
        self.assertEqual(response.status_code, 302) # Redirects
        self.assertTrue(ProjectPhaseConfig.objects.filter(phase_name='New Phase').exists())
        
        # Update
        new_phase = ProjectPhaseConfig.objects.get(phase_name='New Phase')
        response = self.client.post(f'/projects/phases/{new_phase.id}/edit/', {
            'phase_name': 'Updated Phase',
            'progress_percentage': 100,
            'order_index': 10,
            'is_active': True
        })
        self.assertEqual(response.status_code, 302)
        new_phase.refresh_from_db()
        self.assertEqual(new_phase.phase_name, 'Updated Phase')
        
        # Delete
        response = self.client.post(f'/projects/phases/{new_phase.id}/delete/')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ProjectPhaseConfig.objects.filter(id=new_phase.id).exists())

    def test_project_phase_update(self):
        # Update phase
        response = self.client.post(f'/projects/{self.project.id}/update-phase/', {
            'phase_id': self.phase2.id
        })
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.current_phase, self.phase2)
        self.assertEqual(self.project.overall_progress, 50.00)
        
        # Check logs
        self.assertTrue(ProjectPhaseChangeLog.objects.filter(project=self.project).exists())
        
        # Check notifications
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Project Phase Changed', mail.outbox[0].subject)
        self.assertIn('user@example.com', mail.outbox[0].to)

    def test_permission_denied(self):
        self.client.force_login(self.user) # Non-admin
        
        # Admin pages
        response = self.client.get('/projects/phases/')
        self.assertEqual(response.status_code, 403)
        
        # Project update (user is owner, should be allowed)
        response = self.client.post(f'/projects/{self.project.id}/update-phase/', {
            'phase_id': self.phase2.id
        })
        self.assertEqual(response.status_code, 200)
        
        # Create another user and try to update
        other_user = User.objects.create_user('other', 'other@example.com', 'password')
        self.client.force_login(other_user)
        response = self.client.post(f'/projects/{self.project.id}/update-phase/', {
            'phase_id': self.phase1.id
        })
        self.assertEqual(response.status_code, 403)
