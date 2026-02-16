from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from core.models import Role, Permission, UserRole, RolePermission

class RBACService:
    """
    基于角色的访问控制 (RBAC) 服务类。
    提供了用户权限的查询、验证、缓存管理以及角色分配等核心功能。
    支持全局角色和基于范围 (Scope) 的角色（如项目级角色）。
    """
    CACHE_TIMEOUT = 3600  # 缓存过期时间：1小时
    CACHE_PREFIX = "rbac"

    @classmethod
    def _get_cache_key(cls, user_id, scope=None):
        """
        生成权限缓存的键名。
        
        Args:
            user_id (int): 用户ID
            scope (str, optional): 权限范围 (例如 "project:1")。默认为 None (全局)。
            
        Returns:
            str: 格式化的缓存键名
        """
        scope_key = scope if scope else "global"
        return f"{cls.CACHE_PREFIX}:user:{user_id}:scope:{scope_key}"

    @classmethod
    def clear_user_cache(cls, user_id, scope=None):
        """
        清除指定用户的权限缓存。
        
        Args:
            user_id (int): 用户ID
            scope (str, optional): 指定要清除的权限范围。
                                   如果提供了 scope，除了清除该 scope 的缓存外，
                                   还会强制清除全局缓存，因为全局角色可能影响所有范围。
        """
        key = cls._get_cache_key(user_id, scope)
        cache.delete(key)
        
        # 如果指定了特定 scope，同时也清除全局缓存，确保数据一致性
        if scope:
            cache.delete(cls._get_cache_key(user_id, None))

    @classmethod
    def get_user_permissions(cls, user, scope=None):
        """
        获取用户在指定范围内的所有权限代码集合。
        
        该方法会合并以下来源的权限：
        1. 用户拥有的全局角色赋予的权限 (scope=None)
        2. 用户在指定 scope 下拥有的角色赋予的权限
        3. 上述角色通过继承关系 (Parent Role) 获得的权限
        
        Args:
            user (User): 用户对象
            scope (str, optional): 权限范围标识 (如 "project:10")。默认为 None。
            
        Returns:
            set: 包含所有权限代码 (code) 的集合。
                 如果用户是超级管理员，返回 {'*'}。
                 如果用户未登录，返回空集合。
                 
        注意:
            - 结果会被缓存以提高性能。
            - 包含防止角色继承死循环的深度限制逻辑。
        """
        if not user.is_authenticated:
            return set()

        if user.is_superuser:
            return {'*'}  # 超级管理员拥有所有权限

        cache_key = cls._get_cache_key(user.id, scope)
        cached_perms = cache.get(cache_key)
        if cached_perms is not None:
            return cached_perms

        # 查询条件：获取该用户拥有的所有相关 UserRole
        # 1. 全局角色 (scope 为空)：适用于任何场景
        # 2. 指定 Scope 的角色：仅适用于当前场景
        query = Q(user=user) & (Q(scope__isnull=True) | Q(scope=''))
        if scope:
            query |= (Q(user=user) & Q(scope=scope))
        
        user_roles = UserRole.objects.filter(query).select_related('role')
        
        # 收集所有角色（处理角色继承）
        all_roles = set()
        queue = [ur.role for ur in user_roles]
        
        # 安全机制：设置最大递归深度，防止因循环继承导致的无限循环
        max_depth = 20
        depth = 0
        
        while queue and depth < max_depth:
            # 处理当前层级的角色
            level_size = len(queue)
            for _ in range(level_size):
                role = queue.pop(0)
                if role in all_roles:
                    continue
                all_roles.add(role)
                # 如果该角色有父角色，将父角色加入队列继续处理（子角色继承父角色的权限）
                if role.parent:
                    queue.append(role.parent)
            depth += 1
            
        if depth >= max_depth:
            # 潜在风险：角色继承层级过深或存在循环引用
            # 在此仅做记录或忽略，避免系统崩溃
            pass

        # 收集权限代码
        if all_roles:
            role_ids = [r.id for r in all_roles]
            # 优化查询：一次性获取所有相关角色的权限代码并去重
            permission_codes = Permission.objects.filter(
                roles__id__in=role_ids
            ).values_list('code', flat=True).distinct()
            
            perms = set(permission_codes)
        else:
            perms = set()

        # 写入缓存
        cache.set(cache_key, perms, cls.CACHE_TIMEOUT)
        return perms
    
    @classmethod
    def has_permission(cls, user, permission_code, scope=None):
        """
        检查用户是否拥有特定权限。
        
        Args:
            user (User): 用户对象
            permission_code (str): 权限代码 (如 "project.view")
            scope (str, optional): 权限范围 (如 "project:1")
            
        Returns:
            bool: 如果用户拥有该权限（或拥有 '*' 全权限），返回 True；否则返回 False。
        """
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
            
        perms = cls.get_user_permissions(user, scope)
        # 检查是否拥有通配符权限或具体权限
        if '*' in perms:
            return True
        return permission_code in perms

    @classmethod
    def get_scopes_with_permission(cls, user, permission_code):
        """
        反向查询：获取用户在哪些 Scope 下拥有指定权限。
        通常用于列表过滤，例如 "查询我拥有管理权限的所有项目ID"。
        
        Args:
            user (User): 用户对象
            permission_code (str): 目标权限代码
            
        Returns:
            list: 包含 Scope 字符串的列表 (如 ['project:1', 'project:2'])。
                  如果用户是超级管理员或拥有全局该权限，逻辑可能需要特殊处理（此处仅返回明确分配的 scope）。
        """
        if not user.is_authenticated:
            return []
        
        # 1. 查找所有直接拥有此权限（或 '*'）的角色
        roles_with_perm = Role.objects.filter(
            Q(permissions__code=permission_code) | Q(permissions__code='*')
        ).distinct()
        
        # 2. 处理角色继承：
        # 如果角色 A 拥有权限 X，且角色 B 继承自 A (B -> A)，则拥有角色 B 的用户也拥有权限 X。
        # 因此，我们需要找到所有 "祖先" 是上述角色的角色。
        # 换句话说，我们需要找到所有能推导出的目标角色集合。
        
        base_role_ids = list(roles_with_perm.values_list('id', flat=True))
        all_target_role_ids = set(base_role_ids)
        
        # 迭代查找所有子角色（向下查找）
        # 如果 Parent 在列表中，则 Child 也应加入列表（因为 Child 继承 Parent 的能力）
        # 注意：Role.parent 指向父角色。Role B (child) .parent = Role A (parent).
        # 查询 parent_id 在 current_ids 中的角色，即为子角色。
        current_ids = base_role_ids
        while current_ids:
            children = Role.objects.filter(parent_id__in=current_ids).values_list('id', flat=True)
            new_children = [cid for cid in children if cid not in all_target_role_ids]
            if not new_children:
                break
            all_target_role_ids.update(new_children)
            current_ids = new_children
            
        # 3. 查找用户在哪些 Scope 下拥有这些角色
        user_roles = UserRole.objects.filter(
            user=user,
            role_id__in=all_target_role_ids
        ).values_list('scope', flat=True).distinct()
        
        return list(user_roles)

    # --- 管理方法 / Management Methods ---

    @classmethod
    @transaction.atomic
    def assign_role(cls, user, role, scope=None):
        """
        给用户分配角色。
        
        Args:
            user (User): 目标用户
            role (Role): 角色对象
            scope (str, optional): 作用范围
        """
        UserRole.objects.get_or_create(user=user, role=role, scope=scope)
        cls.clear_user_cache(user.id, scope)

    @classmethod
    @transaction.atomic
    def remove_role(cls, user, role, scope=None):
        """
        移除用户的角色。
        
        Args:
            user (User): 目标用户
            role (Role): 角色对象
            scope (str, optional): 作用范围
        """
        UserRole.objects.filter(user=user, role=role, scope=scope).delete()
        cls.clear_user_cache(user.id, scope)

    @classmethod
    @transaction.atomic
    def create_role(cls, name, code, description="", parent=None):
        """
        创建新角色。
        
        Args:
            name (str): 角色名称
            code (str): 角色唯一代码
            description (str): 描述
            parent (Role, optional): 父角色（用于继承）
            
        Returns:
            Role: 创建或获取的角色对象
        """
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
        """
        创建新权限。
        
        Args:
            name (str): 权限名称
            code (str): 权限唯一代码
            group (str): 权限分组
            
        Returns:
            Permission: 创建或获取的权限对象
        """
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
        """
        将权限授予角色。
        
        会触发缓存清理：清除所有拥有该角色的用户的权限缓存。
        """
        RolePermission.objects.get_or_create(role=role, permission=permission)
        
        # 优化：清除所有拥有此角色的用户的缓存
        # 这是一个相对昂贵的操作，但在权限配置变更时是必要的
        user_ids = UserRole.objects.filter(role=role).values_list('user_id', flat=True).distinct()
        for uid in user_ids:
            cls.clear_user_all_scopes(uid)

    @classmethod
    @transaction.atomic
    def revoke_permission_from_role(cls, role, permission):
        """
        从角色撤销权限。
        
        会触发缓存清理。
        """
        RolePermission.objects.filter(role=role, permission=permission).delete()
        
        # 缓存失效逻辑同上
        user_ids = UserRole.objects.filter(role=role).values_list('user_id', flat=True).distinct()
        for uid in user_ids:
            cls.clear_user_all_scopes(uid)

    @classmethod
    def clear_user_all_scopes(cls, user_id):
        """
        辅助方法：清除指定用户的所有 Scope 缓存。
        
        注意：这需要查询数据库来找出用户涉及的所有 Scope，以确保清理干净。
        """
        scopes = UserRole.objects.filter(user_id=user_id).values_list('scope', flat=True).distinct()
        cls.clear_user_cache(user_id, None) # 清除全局
        for scope in scopes:
            cls.clear_user_cache(user_id, scope)
