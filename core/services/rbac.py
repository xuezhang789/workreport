from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from core.models import Role, Permission, UserRole, RolePermission

class RBACService:
    CACHE_TIMEOUT = 3600  # 1 hour
    CACHE_PREFIX = "rbac"

    @classmethod
    def _get_cache_key(cls, user_id, scope=None):
        scope_key = scope if scope else "global"
        return f"{cls.CACHE_PREFIX}:user:{user_id}:scope:{scope_key}"

    @classmethod
    def clear_user_cache(cls, user_id, scope=None):
        """清除用户权限缓存"""
        key = cls._get_cache_key(user_id, scope)
        cache.delete(key)
        # Also clear global cache if scope is provided, as global roles apply everywhere
        if scope:
            cache.delete(cls._get_cache_key(user_id, None))

    @classmethod
    def get_user_permissions(cls, user, scope=None):
        """
        获取用户在指定范围内的所有权限代码集合。
        包含：
        1. 全局角色赋予的权限
        2. 指定Scope赋予的权限
        3. 角色继承带来的权限
        """
        if not user.is_authenticated:
            return set()

        if user.is_superuser:
            return {'*'}  # Superuser has all permissions

        cache_key = cls._get_cache_key(user.id, scope)
        cached_perms = cache.get(cache_key)
        if cached_perms is not None:
            return cached_perms

        # Fetch roles: Global (scope=None) OR Scoped
        # Note: Global roles apply to ALL scopes.
        query = Q(user=user) & (Q(scope__isnull=True) | Q(scope=''))
        if scope:
            query |= (Q(user=user) & Q(scope=scope))
        
        user_roles = UserRole.objects.filter(query).select_related('role')
        
        # Collect all roles (including parents)
        all_roles = set()
        queue = [ur.role for ur in user_roles]
        
        while queue:
            role = queue.pop(0)
            if role in all_roles:
                continue
            all_roles.add(role)
            if role.parent:
                queue.append(role.parent)

        # Collect permissions
        perms = set()
        for role in all_roles:
            # Optimize: This loop might cause N+1 if not careful. 
            # Ideally we'd fetch all RolePermissions for these roles in one go.
            pass
        
        if all_roles:
            role_ids = [r.id for r in all_roles]
            permission_codes = Permission.objects.filter(
                rolepermission__role_id__in=role_ids
            ).values_list('code', flat=True).distinct()
            perms.update(permission_codes)

        cache.set(cache_key, perms, cls.CACHE_TIMEOUT)
        return perms

    @classmethod
    def has_permission(cls, user, permission_code, scope=None):
        """
        检查用户是否有特定权限
        """
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
            
        perms = cls.get_user_permissions(user, scope)
        if '*' in perms:
            return True
        return permission_code in perms

    @classmethod
    def get_scopes_with_permission(cls, user, permission_code):
        """
        获取用户拥有特定权限的所有 Scope 列表。
        主要用于列表过滤，例如 '获取所有我能管理的项目ID'。
        """
        if not user.is_authenticated:
            return []
        
        # 1. Find all roles that have this permission
        roles_with_perm = Role.objects.filter(
            Q(permissions__code=permission_code) | Q(permissions__code='*')
        ).distinct()
        
        # Also include roles that inherit from these roles?
        # If Child inherits from Parent, and Parent has Perm, then Child has Perm.
        # So we need to find all Roles R where R or any of its Parents have Perm.
        # This is complex to query inversely without recursive CTEs.
        # Simplified approach:
        # Fetch all roles in memory, build inheritance tree, find target roles.
        # Or: Rely on `permissions__code` query which SHOULD handle ManyToMany correctly if we didn't use 'through' manually with extra logic.
        # Since we use standard M2M with through, standard filter works for direct assignment.
        # But inheritance is manual via `parent` FK.
        # If Role A (Parent) has Perm X. Role B (Child) has Parent A.
        # Role B does NOT have Perm X in RolePermission table.
        # So `roles_with_perm` will only return A.
        # But User might have Role B.
        # So we need to find all descendants of A as well.
        
        base_role_ids = list(roles_with_perm.values_list('id', flat=True))
        all_target_role_ids = set(base_role_ids)
        
        # Iteratively find children
        current_ids = base_role_ids
        while current_ids:
            children = Role.objects.filter(parent_id__in=current_ids).values_list('id', flat=True)
            new_children = [cid for cid in children if cid not in all_target_role_ids]
            if not new_children:
                break
            all_target_role_ids.update(new_children)
            current_ids = new_children
            
        # 2. Find UserRoles for these roles
        user_roles = UserRole.objects.filter(
            user=user,
            role_id__in=all_target_role_ids
        ).values_list('scope', flat=True).distinct()
        
        return list(user_roles)

    # --- Management Methods ---

    @classmethod
    @transaction.atomic
    def assign_role(cls, user, role, scope=None):
        """赋予用户角色"""
        UserRole.objects.get_or_create(user=user, role=role, scope=scope)
        cls.clear_user_cache(user.id, scope)

    @classmethod
    @transaction.atomic
    def remove_role(cls, user, role, scope=None):
        """移除用户角色"""
        UserRole.objects.filter(user=user, role=role, scope=scope).delete()
        cls.clear_user_cache(user.id, scope)

    @classmethod
    @transaction.atomic
    def create_role(cls, name, code, description="", parent=None):
        role, created = Role.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'description': description,
                'parent': parent
            }
        )
        return role

    @classmethod
    @transaction.atomic
    def create_permission(cls, name, code, group=""):
        perm, created = Permission.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'group': group
            }
        )
        return perm

    @classmethod
    @transaction.atomic
    def grant_permission_to_role(cls, role, permission):
        RolePermission.objects.get_or_create(role=role, permission=permission)
        # Invalidate cache for all users with this role? 
        # This is expensive (scan UserRole). 
        # For now, we accept eventual consistency or implement a versioning strategy.
        # Or clear all RBAC cache if role definition changes (simple but heavy).
        # Better: Do nothing and let TTL expire, or provide a 'flush_all' admin tool.
        # For critical updates, we can bump a global version key in cache keys.
        pass
