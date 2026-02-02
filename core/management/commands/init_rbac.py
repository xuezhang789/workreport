from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Role, Permission, UserRole, RolePermission, Profile
from core.services.rbac import RBACService
from projects.models import Project

class Command(BaseCommand):
    help = '初始化 RBAC 角色和权限，并迁移现有项目数据。'

    def handle(self, *args, **options):
        self.stdout.write("Initializing RBAC...")

        # 1. Define Permissions
        # 1. 定义权限
        permissions_data = [
            # Project
            # 项目
            {'code': 'project.view', 'name': '查看项目', 'group': 'project'},
            {'code': 'project.manage', 'name': '管理项目', 'group': 'project'}, # Edit, Delete, Manage Members | 编辑，删除，管理成员
            # Task
            # 任务
            {'code': 'task.view', 'name': '查看任务', 'group': 'task'},
            {'code': 'task.create', 'name': '创建任务', 'group': 'task'},
            {'code': 'task.edit', 'name': '编辑任务', 'group': 'task'},
            {'code': 'task.delete', 'name': '删除任务', 'group': 'task'},
            # Report
            # 日报
            {'code': 'report.view', 'name': '查看日报', 'group': 'report'},
        ]

        created_perms = {}
        for p_data in permissions_data:
            perm = RBACService.create_permission(p_data['name'], p_data['code'], p_data['group'])
            created_perms[p_data['code']] = perm
            self.stdout.write(f"  Permission: {perm.code}")

        # 2. Define Roles
        # 2. 定义角色
        roles_data = [
            {
                'code': 'project_owner', 
                'name': 'Project Owner', 
                'perms': ['project.view', 'project.manage', 'task.view', 'task.create', 'task.edit', 'task.delete', 'report.view']
            },
            {
                'code': 'project_manager', 
                'name': 'Project Manager', 
                'perms': ['project.view', 'project.manage', 'task.view', 'task.create', 'task.edit', 'task.delete', 'report.view']
            },
            {
                'code': 'project_member', 
                'name': 'Project Member', 
                'perms': ['project.view', 'task.view', 'task.create', 'report.view']
            },
            {
                'code': 'global_manager',
                'name': 'Global Manager',
                'perms': ['project.view', 'project.manage', 'task.view', 'task.create', 'task.edit', 'task.delete', 'report.view']
            },
        ]

        created_roles = {}
        for r_data in roles_data:
            role = RBACService.create_role(r_data['name'], r_data['code'])
            created_roles[r_data['code']] = role
            self.stdout.write(f"  Role: {role.code}")
            
            # Assign permissions
            # 分配权限
            for p_code in r_data['perms']:
                if p_code in created_perms:
                    RBACService.grant_permission_to_role(role, created_perms[p_code])

        # 3. Migrate Project Data
        # 3. 迁移项目数据
        self.stdout.write("Migrating Project Permissions...")
        
        projects = Project.objects.all()
        count = 0
        
        with transaction.atomic():
            for project in projects:
                scope = f"project:{project.id}"
                
                # Owner
                # 所有者
                if project.owner:
                    RBACService.assign_role(project.owner, created_roles['project_owner'], scope)
                    
                # Managers
                # 经理
                for user in project.managers.all():
                    RBACService.assign_role(user, created_roles['project_manager'], scope)
                    
                # Members
                # 成员
                for user in project.members.all():
                    RBACService.assign_role(user, created_roles['project_member'], scope)
                    
                count += 1
                if count % 10 == 0:
                    self.stdout.write(f"  Processed {count} projects...")

        # 4. Migrate Profile Positions
        # 4. 迁移个人资料职位
        self.stdout.write("Migrating Profile Positions...")
        profiles = Profile.objects.filter(position__in=['mgr', 'pm'])
        for profile in profiles:
            RBACService.assign_role(profile.user, created_roles['global_manager'], scope=None)
            self.stdout.write(f"  Assigned Global Manager to {profile.user.username}")

        self.stdout.write(self.style.SUCCESS(f"Successfully initialized RBAC and migrated {count} projects."))
