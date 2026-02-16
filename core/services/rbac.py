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
        # 如果提供了 scope，也清除全局缓存，因为全局角色适用于任何地方
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
        # 获取角色：全局（scope=None）或指定范围
        # 注意：全局角色适用于所有范围。
        query = Q(user=user) & (Q(scope__isnull=True) | Q(scope=''))
        if scope:
            query |= (Q(user=user) & Q(scope=scope))
        
        user_roles = UserRole.objects.filter(query).select_related('role')
        
        # Collect all roles (including parents)
        # 收集所有角色（包括父角色）
        all_roles = set()
        queue = [ur.role for ur in user_roles]
        
        # Security: Prevent infinite recursion if roles have circular inheritance
        # 安全：防止角色循环继承导致的无限递归
        max_depth = 20
        depth = 0
        
        while queue and depth < max_depth:
            # Process current level
            level_size = len(queue)
            for _ in range(level_size):
                role = queue.pop(0)
                if role in all_roles:
                    continue
                all_roles.add(role)
                if role.parent:
                    queue.append(role.parent)
            depth += 1
            
        if depth >= max_depth:
            # Log warning about potential cycle or too deep hierarchy
            pass

        # Collect permissions
        # 收集权限
        if all_roles:
            role_ids = [r.id for r in all_roles]
            # Optimized query: fetch all permission codes for these roles in one go
            # 优化查询：一次性获取这些角色的所有权限代码
            permission_codes = Permission.objects.filter(
                roles__id__in=role_ids
            ).values_list('code', flat=True).distinct()
            
            perms = set(permission_codes)
        else:
            perms = set()

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
        # 1. 查找所有拥有此权限的角色
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
        # 是否也包含继承自这些角色的角色？
        # 如果子角色继承自父角色，且父角色拥有权限，则子角色也拥有权限。
        # 因此我们需要找到所有角色 R，其中 R 或其任何父角色拥有权限。
        # 如果没有递归 CTE，反向查询会很复杂。
        # 简化方法：
        # 在内存中获取所有角色，构建继承树，查找目标角色。
        # 或者：依赖 permissions__code 查询，如果我们没有手动使用 'through' 并带有额外逻辑，它应该能正确处理 ManyToMany。
        # 但继承是通过 parent 外键手动实现的。
        # 如果角色 A（父）拥有权限 X。角色 B（子）拥有父角色 A。
        # 角色 B 在 RolePermission 表中没有权限 X。
        # 所以 roles_with_perm 只会返回 A。
        # 但用户可能拥有角色 B。
        # 因此我们也需要找到 A 的所有后代。
        
        base_role_ids = list(roles_with_perm.values_list('id', flat=True))
        all_target_role_ids = set(base_role_ids)
        
        # Iteratively find children
        # 迭代查找子角色
        current_ids = base_role_ids
        while current_ids:
            children = Role.objects.filter(parent_id__in=current_ids).values_list('id', flat=True)
            new_children = [cid for cid in children if cid not in all_target_role_ids]
            if not new_children:
                break
            all_target_role_ids.update(new_children)
            current_ids = new_children
            
        # 2. Find UserRoles for these roles
        # 2. 查找这些角色的 UserRoles
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
        # Optimization: Clear cache for all users holding this role
        # We find users with this role (in any scope) and clear their cache.
        user_ids = UserRole.objects.filter(role=role).values_list('user_id', flat=True).distinct()
        for uid in user_ids:
            cls.clear_user_all_scopes(uid)

    @classmethod
    @transaction.atomic
    def revoke_permission_from_role(cls, role, permission):
        RolePermission.objects.filter(role=role, permission=permission).delete()
        # Same cache invalidation logic as grant
        user_ids = UserRole.objects.filter(role=role).values_list('user_id', flat=True).distinct()
        for uid in user_ids:
            cls.clear_user_all_scopes(uid)

    @classmethod
    def clear_user_all_scopes(cls, user_id):
        # Helper to clear main cache keys.
        # Note: This is an approximation. If user has many scopes, we might miss some if we don't query DB.
        # But we CAN query DB.
        scopes = UserRole.objects.filter(user_id=user_id).values_list('scope', flat=True).distinct()
        cls.clear_user_cache(user_id, None) # Global
        for scope in scopes:
            cls.clear_user_cache(user_id, scope)
