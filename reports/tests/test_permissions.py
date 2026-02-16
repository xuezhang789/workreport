from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.core.cache import cache
from django.template import Context, Template
from reports.utils import can_manage_project, get_accessible_projects
from projects.models import Project
from core.services.rbac import RBACService

class PermissionUtilsTest(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        
        # Create Standard Roles
        self.role_owner = RBACService.create_role('Project Owner', 'project_owner')
        self.role_manager = RBACService.create_role('Project Manager', 'project_manager')
        self.role_member = RBACService.create_role('Project Member', 'project_member')
        
        self.perm_view = RBACService.create_permission('View Project', 'project.view', 'project')
        self.perm_manage = RBACService.create_permission('Manage Project', 'project.manage', 'project')
        
        RBACService.grant_permission_to_role(self.role_owner, self.perm_view)
        RBACService.grant_permission_to_role(self.role_owner, self.perm_manage)
        
        RBACService.grant_permission_to_role(self.role_manager, self.perm_view)
        RBACService.grant_permission_to_role(self.role_manager, self.perm_manage)
        
        RBACService.grant_permission_to_role(self.role_member, self.perm_view)

        # Users
        self.superuser = User.objects.create_superuser('admin', 'admin@example.com', 'password')
        self.owner = User.objects.create_user('owner', 'owner@example.com', 'password')
        self.manager = User.objects.create_user('manager', 'manager@example.com', 'password')
        self.member = User.objects.create_user('member', 'member@example.com', 'password')
        self.outsider = User.objects.create_user('outsider', 'outsider@example.com', 'password')
        
        # Project (Signals will assign roles)
        self.project = Project.objects.create(name="Test Project", code="TP", owner=self.owner)
        self.project.managers.add(self.manager)
        self.project.members.add(self.member)
        
        # Additional manual assignment for test specific scenario
        # Assign RBAC Role to Member (upgrade to Manager via RBAC)
        # Note: The member already has 'project_member' via signal.
        # We add 'project_manager' manually here.
        RBACService.assign_role(self.member, self.role_manager, scope=f"project:{self.project.id}")

    def test_can_manage_project_superuser(self):
        self.assertTrue(can_manage_project(self.superuser, self.project))

    def test_can_manage_project_owner(self):
        self.assertTrue(can_manage_project(self.owner, self.project))

    def test_can_manage_project_legacy_manager(self):
        self.assertTrue(can_manage_project(self.manager, self.project))

    def test_can_manage_project_rbac_manager(self):
        # Member has 'project_manager' role in this scope
        self.assertTrue(can_manage_project(self.member, self.project))

    def test_cannot_manage_project_outsider(self):
        self.assertFalse(can_manage_project(self.outsider, self.project))

    def test_get_accessible_projects(self):
        # Superuser sees all
        self.assertIn(self.project, get_accessible_projects(self.superuser))
        
        # Owner sees project
        self.assertIn(self.project, get_accessible_projects(self.owner))
        
        # Manager sees project
        self.assertIn(self.project, get_accessible_projects(self.manager))
        
        # Member sees project
        self.assertIn(self.project, get_accessible_projects(self.member))
        
        # Outsider sees nothing
        self.assertFalse(get_accessible_projects(self.outsider).exists())

    def test_permission_tags(self):
        # Test template tag rendering
        template_str = """
        {% load permission_tags %}
        {% can_manage_project project as can_manage %}
        {% if can_manage %}YES{% else %}NO{% endif %}
        """
        template = Template(template_str)
        
        # Context for Owner
        request = self.factory.get('/')
        request.user = self.owner
        context = Context({'project': self.project, 'request': request})
        rendered = template.render(context)
        self.assertIn("YES", rendered.strip())
        
        # Context for Outsider
        request.user = self.outsider
        context = Context({'project': self.project, 'request': request})
        rendered = template.render(context)
        self.assertIn("NO", rendered.strip())
