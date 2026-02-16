
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from projects.models import Project
from tasks.models import Task
from core.permissions import has_manage_permission
from reports.utils import can_manage_project, get_accessible_projects
from core.models import Role, Permission, RolePermission, Profile
from core.services.rbac import RBACService

class PermissionRefactorTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.client = Client()
        
        # 1. Setup RBAC Roles and Permissions
        self.perm_view = Permission.objects.create(code='project.view', name='View Project')
        self.perm_manage = Permission.objects.create(code='project.manage', name='Manage Project')
        
        self.role_owner = Role.objects.create(code='project_owner', name='Project Owner')
        self.role_manager = Role.objects.create(code='project_manager', name='Project Manager')
        self.role_member = Role.objects.create(code='project_member', name='Project Member')
        
        RolePermission.objects.create(role=self.role_owner, permission=self.perm_manage)
        RolePermission.objects.create(role=self.role_owner, permission=self.perm_view)
        
        RolePermission.objects.create(role=self.role_manager, permission=self.perm_manage)
        RolePermission.objects.create(role=self.role_manager, permission=self.perm_view)
        
        RolePermission.objects.create(role=self.role_member, permission=self.perm_view)

        # 2. Create Users and Profiles
        self.superuser = self.User.objects.create_superuser('admin', 'admin@example.com', 'password')
        Profile.objects.create(user=self.superuser, position='mgr')
        
        self.owner = self.User.objects.create_user('owner', 'owner@example.com', 'password')
        Profile.objects.create(user=self.owner, position='mgr')
        
        self.manager = self.User.objects.create_user('manager', 'manager@example.com', 'password')
        Profile.objects.create(user=self.manager, position='pm')
        
        self.member = self.User.objects.create_user('member', 'member@example.com', 'password')
        Profile.objects.create(user=self.member, position='dev')
        
        self.outsider = self.User.objects.create_user('outsider', 'outsider@example.com', 'password')
        Profile.objects.create(user=self.outsider, position='dev')
        
        # 3. Create Project
        self.project = Project.objects.create(
            name='Test Project',
            code='TP',
            owner=self.owner
        )
        # Signals might fail in test env for M2M, so we manually assign roles to be sure
        self.project.managers.add(self.manager)
        self.project.members.add(self.member)
        
        # Manual RBAC Assignment (Workaround for Signal issues in Test)
        scope = f"project:{self.project.id}"
        RBACService.assign_role(self.owner, self.role_owner, scope)
        RBACService.assign_role(self.manager, self.role_manager, scope)
        RBACService.assign_role(self.member, self.role_member, scope)
        
        # 4. Create Task
        self.task = Task.objects.create(
            title='Test Task',
            project=self.project,
            user=self.member,
            status='todo',
            priority='medium'
        )

    def test_core_permissions_import(self):
        """Test that has_manage_permission is importable and works"""
        self.assertTrue(has_manage_permission(self.superuser))
        self.assertFalse(has_manage_permission(self.member))

    def test_reports_utils_can_manage_project(self):
        """Test can_manage_project logic"""
        self.assertTrue(can_manage_project(self.superuser, self.project))
        self.assertTrue(can_manage_project(self.owner, self.project))
        self.assertTrue(can_manage_project(self.manager, self.project))
        self.assertFalse(can_manage_project(self.member, self.project))
        self.assertFalse(can_manage_project(self.outsider, self.project))

    def test_reports_utils_get_accessible_projects(self):
        """Test get_accessible_projects logic"""
        self.assertIn(self.project, get_accessible_projects(self.superuser))
        self.assertIn(self.project, get_accessible_projects(self.owner))
        self.assertIn(self.project, get_accessible_projects(self.manager))
        self.assertIn(self.project, get_accessible_projects(self.member))
        self.assertNotIn(self.project, get_accessible_projects(self.outsider))

    def test_task_view_permission(self):
        """Test task detail view permission enforcement"""
        url = f'/tasks/{self.task.id}/view/'
        
        # Member can view
        self.client.force_login(self.member)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        
        # Outsider cannot view
        self.client.force_login(self.outsider)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_task_edit_permission(self):
        """Test task edit permission enforcement"""
        url = f'/tasks/{self.task.id}/edit/'
        
        # Manager can edit
        self.client.force_login(self.manager)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        
        # Member (who is owner of task) can edit
        self.client.force_login(self.member)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        
        # Create another member who is NOT task owner
        other_member = self.User.objects.create_user('other', 'other@example.com', 'password')
        Profile.objects.create(user=other_member, position='dev')
        self.project.members.add(other_member)
        
        # Manually assign role for test stability
        scope = f"project:{self.project.id}"
        RBACService.assign_role(other_member, self.role_member, scope)
        
        self.client.force_login(other_member)
        resp = self.client.get(url)
        # Should be forbidden (403)
        self.assertEqual(resp.status_code, 403)
