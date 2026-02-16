from django.test import TestCase
from django.contrib.auth.models import User
from reports.models import Project
from core.models import Role, UserRole

class ProjectSignalTests(TestCase):
    def setUp(self):
        # Create Roles
        self.role_owner = Role.objects.create(code='project_owner', name='Project Owner')
        self.role_manager = Role.objects.create(code='project_manager', name='Project Manager')
        self.role_member = Role.objects.create(code='project_member', name='Project Member')

        # Create Users
        self.u_owner = User.objects.create_user('owner', 'owner@test.com', 'pass')
        self.u_manager = User.objects.create_user('manager', 'manager@test.com', 'pass')
        self.u_member = User.objects.create_user('member', 'member@test.com', 'pass')

    def test_owner_role_assignment(self):
        """Test that creating a project assigns the owner role."""
        p1 = Project.objects.create(name='P1', code='P1', owner=self.u_owner)
        
        # Check if owner has the role
        self.assertTrue(UserRole.objects.filter(
            user=self.u_owner, 
            role=self.role_owner, 
            scope=f"project:{p1.id}"
        ).exists())

        # Change owner
        p1.owner = self.u_member
        p1.save()
        
        # Old owner should lose the role (or keep it? Logic says remove)
        self.assertFalse(UserRole.objects.filter(
            user=self.u_owner, 
            role=self.role_owner, 
            scope=f"project:{p1.id}"
        ).exists())
        
        # New owner should have the role
        self.assertTrue(UserRole.objects.filter(
            user=self.u_member, 
            role=self.role_owner, 
            scope=f"project:{p1.id}"
        ).exists())

    def test_member_role_assignment(self):
        """Test that adding a member assigns the member role."""
        p1 = Project.objects.create(name='P1', code='P1', owner=self.u_owner)
        
        # Add member
        p1.members.add(self.u_member)
        
        # Check role
        self.assertTrue(UserRole.objects.filter(
            user=self.u_member, 
            role=self.role_member, 
            scope=f"project:{p1.id}"
        ).exists())
        
        # Remove member
        p1.members.remove(self.u_member)
        
        # Check role removed
        self.assertFalse(UserRole.objects.filter(
            user=self.u_member, 
            role=self.role_member, 
            scope=f"project:{p1.id}"
        ).exists())

    def test_manager_role_assignment(self):
        """Test that adding a manager assigns the manager role."""
        p1 = Project.objects.create(name='P1', code='P1', owner=self.u_owner)
        
        # Add manager
        p1.managers.add(self.u_manager)
        
        # Check role
        self.assertTrue(UserRole.objects.filter(
            user=self.u_manager, 
            role=self.role_manager, 
            scope=f"project:{p1.id}"
        ).exists())
        
        # Remove manager
        p1.managers.remove(self.u_manager)
        
        # Check role removed
        self.assertFalse(UserRole.objects.filter(
            user=self.u_manager, 
            role=self.role_manager, 
            scope=f"project:{p1.id}"
        ).exists())
