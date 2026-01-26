from django.test import TestCase, Client
from django.contrib.auth.models import User
from reports.models import Project, Task, Profile
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

class TaskEditPermissionTest(TestCase):
    def setUp(self):
        # Create users
        self.owner = User.objects.create_user(username='owner', password='password')
        Profile.objects.create(user=self.owner, position='pm')
        
        self.collaborator = User.objects.create_user(username='collaborator', password='password')
        Profile.objects.create(user=self.collaborator, position='dev')
        
        self.other = User.objects.create_user(username='other', password='password')
        Profile.objects.create(user=self.other, position='dev')

        # Create project
        self.project = Project.objects.create(
            name="Test Project", 
            code="TP", 
            owner=self.owner,
            is_active=True
        )
        self.project.members.add(self.collaborator)

        # Create task
        self.task = Task.objects.create(
            title="Original Title",
            project=self.project,
            user=self.owner,
            status='pending',
            priority='medium',
            due_at=timezone.now() + timedelta(days=1)
        )
        self.task.collaborators.add(self.collaborator)

        self.client = Client()

    def test_collaborator_view_permission(self):
        """Test that collaborator sees the correct restricted UI"""
        self.client.login(username='collaborator', password='password')
        url = reverse('reports:admin_task_edit', args=[self.task.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_collaborator_only'])
        self.assertContains(response, 'disabled readonly')  # Check for disabled fields in HTML

    def test_collaborator_update_status_allowed(self):
        """Test that collaborator can update status"""
        self.client.login(username='collaborator', password='password')
        url = reverse('reports:admin_task_edit', args=[self.task.id])
        
        # Post data with ONLY status changed (and other fields as they are, or omitted/ignored)
        # Note: In our implementation, if is_collaborator_only, other fields are ignored if they match existing.
        # If they don't match, 403.
        # If they are missing, the view uses existing values.
        
        response = self.client.post(url, {
            'status': 'in_progress',
            # Even if we don't send title, the view handles it by using task.title
        })
        
        self.assertEqual(response.status_code, 302)  # Redirect means success
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, 'in_progress')
        self.assertEqual(self.task.title, "Original Title") # Unchanged

    def test_collaborator_update_title_forbidden(self):
        """Test that collaborator cannot update title"""
        self.client.login(username='collaborator', password='password')
        url = reverse('reports:admin_task_edit', args=[self.task.id])
        
        response = self.client.post(url, {
            'title': 'Hacked Title',
            'status': 'in_progress'
        })
        
        self.assertEqual(response.status_code, 403)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Original Title")

    def test_collaborator_update_project_forbidden(self):
        """Test that collaborator cannot move project"""
        self.client.login(username='collaborator', password='password')
        url = reverse('reports:admin_task_edit', args=[self.task.id])
        
        # Create another project
        other_project = Project.objects.create(name="Other", code="OP", owner=self.owner)
        
        response = self.client.post(url, {
            'project': other_project.id,
            'status': 'in_progress'
        })
        
        self.assertEqual(response.status_code, 403)

    def test_collaborator_update_assignee_forbidden(self):
        """Test that collaborator cannot change assignee"""
        self.client.login(username='collaborator', password='password')
        url = reverse('reports:admin_task_edit', args=[self.task.id])
        
        response = self.client.post(url, {
            'user': self.other.id,
            'status': 'in_progress'
        })
        
        self.assertEqual(response.status_code, 403)
        
    def test_owner_full_access(self):
        """Test that owner has full access"""
        self.client.login(username='owner', password='password')
        url = reverse('reports:admin_task_edit', args=[self.task.id])
        
        response = self.client.get(url)
        self.assertFalse(response.context['is_collaborator_only'])
        
        # Change title
        response = self.client.post(url, {
            'title': 'New Title by Owner',
            'project': self.project.id,
            'user': self.owner.id,
            'status': 'completed',
            'content': 'Updated content'
        })
        
        self.assertEqual(response.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, 'New Title by Owner')
        self.assertEqual(self.task.status, 'completed')
