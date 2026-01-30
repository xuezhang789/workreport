from django.test import TestCase
from django.contrib.auth.models import User
from django.core.cache import cache
from core.models import Role, Permission, UserRole, RolePermission
from core.services.rbac import RBACService
from reports.utils import can_manage_project, get_accessible_projects, get_manageable_projects
from projects.models import Project

class RBACServiceTest(TestCase):
    def setUp(self):
        # Clear cache
        cache.clear()
        
        # Users
        self.user = User.objects.create_user('testuser', 'test@example.com', 'password')
        self.admin = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        
        # Permissions
        self.perm_view = RBACService.create_permission('View Project', 'project.view', 'project')
        self.perm_edit = RBACService.create_permission('Edit Project', 'project.manage', 'project')
        
        # Roles
        self.role_member = RBACService.create_role('Member', 'member')
        self.role_manager = RBACService.create_role('Manager', 'manager')
        
        # Assign perms
        RBACService.grant_permission_to_role(self.role_member, self.perm_view)
        RBACService.grant_permission_to_role(self.role_manager, self.perm_view)
        RBACService.grant_permission_to_role(self.role_manager, self.perm_edit)
        
        # Project
        self.project = Project.objects.create(name="Test Project", code="TP", owner=self.admin)

    def test_has_permission_basic(self):
        # Assign Member role for project
        scope = f"project:{self.project.id}"
        RBACService.assign_role(self.user, self.role_member, scope)
        
        # Check View
        self.assertTrue(RBACService.has_permission(self.user, 'project.view', scope))
        # Check Manage (Should fail)
        self.assertFalse(RBACService.has_permission(self.user, 'project.manage', scope))
        
        # Check different scope (Should fail)
        self.assertFalse(RBACService.has_permission(self.user, 'project.view', "project:999"))

    def test_has_permission_manager(self):
        scope = f"project:{self.project.id}"
        RBACService.assign_role(self.user, self.role_manager, scope)
        
        self.assertTrue(RBACService.has_permission(self.user, 'project.view', scope))
        self.assertTrue(RBACService.has_permission(self.user, 'project.manage', scope))

    def test_role_inheritance(self):
        # Create SuperManager that inherits from Manager
        role_super = RBACService.create_role('Super Manager', 'super_manager', parent=self.role_manager)
        
        scope = f"project:{self.project.id}"
        RBACService.assign_role(self.user, role_super, scope)
        
        # Should have Manager's permissions
        self.assertTrue(RBACService.has_permission(self.user, 'project.manage', scope))

    def test_global_role(self):
        # Assign Manager globally
        RBACService.assign_role(self.user, self.role_manager, None)
        
        # Should have permission in any scope
        self.assertTrue(RBACService.has_permission(self.user, 'project.manage', f"project:{self.project.id}"))
        self.assertTrue(RBACService.has_permission(self.user, 'project.manage', "project:999"))

    def test_superuser(self):
        self.assertTrue(RBACService.has_permission(self.admin, 'project.manage', "any_scope"))

    def test_get_scopes_with_permission(self):
        p1 = Project.objects.create(name="P1", code="P1", owner=self.admin)
        p2 = Project.objects.create(name="P2", code="P2", owner=self.admin)
        p3 = Project.objects.create(name="P3", code="P3", owner=self.admin)
        
        # User is Manager of P1, Member of P2, Nothing in P3
        RBACService.assign_role(self.user, self.role_manager, f"project:{p1.id}")
        RBACService.assign_role(self.user, self.role_member, f"project:{p2.id}")
        
        # Check 'project.manage'
        scopes = RBACService.get_scopes_with_permission(self.user, 'project.manage')
        self.assertIn(f"project:{p1.id}", scopes)
        self.assertNotIn(f"project:{p2.id}", scopes)
        
        # Check 'project.view'
        scopes_view = RBACService.get_scopes_with_permission(self.user, 'project.view')
        self.assertIn(f"project:{p1.id}", scopes_view)
        self.assertIn(f"project:{p2.id}", scopes_view)

    def test_utils_integration(self):
        # Setup: User is Manager of Project
        scope = f"project:{self.project.id}"
        RBACService.assign_role(self.user, self.role_manager, scope)
        
        # Test can_manage_project
        self.assertTrue(can_manage_project(self.user, self.project))
        
        # Test get_accessible_projects
        projects = get_accessible_projects(self.user)
        self.assertIn(self.project, projects)
        
        # Test get_manageable_projects
        manageable = get_manageable_projects(self.user)
        self.assertIn(self.project, manageable)
        
        # Negative test
        p2 = Project.objects.create(name="P2", code="P2", owner=self.admin)
        self.assertFalse(can_manage_project(self.user, p2))
        self.assertNotIn(p2, get_accessible_projects(self.user))

