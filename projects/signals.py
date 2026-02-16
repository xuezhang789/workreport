
from django.db.models.signals import post_delete, post_save, m2m_changed, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import ProjectAttachment, Project
from core.models import Role, UserRole
from core.services.rbac import RBACService

@receiver(post_delete, sender=ProjectAttachment)
def delete_project_attachment_file(sender, instance, **kwargs):
    """
    当 ProjectAttachment 被删除时，自动从存储中删除对应的文件。
    
    Args:
        sender: 模型类
        instance: 被删除的实例
        **kwargs: 额外参数
    """
    if instance.file:
        instance.file.delete(save=False)

# --- RBAC 同步信号 (RBAC Sync Signals) ---
# 负责将项目模型的变更（所有者、成员、管理员）实时同步到 RBAC 权限系统。

@receiver(pre_save, sender=Project)
def track_old_owner(sender, instance, **kwargs):
    """
    Pre-save 信号：在保存项目前追踪旧的所有者。
    用于在 post_save 中检测所有者是否发生变更。
    """
    if instance.pk:
        try:
            old_instance = Project.objects.get(pk=instance.pk)
            instance._old_owner = old_instance.owner
        except Project.DoesNotExist:
            instance._old_owner = None
    else:
        instance._old_owner = None

@receiver(post_save, sender=Project)
def sync_project_owner_role(sender, instance, created, **kwargs):
    """
    Post-save 信号：当项目所有者变更时，同步 'project_owner' 角色。
    
    逻辑：
    1. 新建项目：给当前所有者分配角色。
    2. 更新项目：如果所有者变更，移除旧所有者的角色，给新所有者分配角色。
    """
    scope = f"project:{instance.id}"
    owner_role = Role.objects.filter(code='project_owner').first()
    
    if not owner_role:
        return

    # 场景1：新建项目
    if created and instance.owner:
        RBACService.assign_role(instance.owner, owner_role, scope)
        return

    # 场景2：所有者变更
    old_owner = getattr(instance, '_old_owner', None)
    new_owner = instance.owner

    if old_owner and old_owner != new_owner:
        RBACService.remove_role(old_owner, owner_role, scope)
    
    if new_owner and new_owner != old_owner:
        RBACService.assign_role(new_owner, owner_role, scope)

@receiver(m2m_changed, sender=Project.members.through)
def sync_project_member_role(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    M2M 变更信号：当项目成员列表发生变化时，同步 'project_member' 角色。
    
    Args:
        sender: 中间表模型 (Project.members.through)
        instance: Project 实例 (reverse=False) 或 User 实例 (reverse=True)
        action: 动作类型 (post_add, post_remove, post_clear)
        reverse: 方向标识
        pk_set: 涉及的主键集合
    """
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return

    # 当 reverse=False (Project -> User)，instance 是 Project
    # 当 reverse=True (User -> Project)，instance 是 User
    # 目前主要处理正向操作 (Project.members.add(user))。
    
    if reverse:
        # 暂不处理反向操作 (user.project_set.add(project))
        pass
    else:
        # instance 是 Project, pk_set 是 User IDs
        project = instance
        scope = f"project:{project.id}"
        member_role = Role.objects.filter(code='project_member').first()
        
        if not member_role:
            return

        if action == 'post_add':
            for user_id in pk_set:
                user = User.objects.get(pk=user_id)
                RBACService.assign_role(user, member_role, scope)
                
        elif action == 'post_remove':
            for user_id in pk_set:
                user = User.objects.get(pk=user_id)
                RBACService.remove_role(user, member_role, scope)
                
        elif action == 'post_clear':
            # 清空该项目下所有的成员角色关联
            # 注意：这需要精确删除，这里简单使用 filter 删除
            UserRole.objects.filter(role=member_role, scope=scope).delete()

@receiver(m2m_changed, sender=Project.managers.through)
def sync_project_manager_role(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    M2M 变更信号：当项目管理员列表发生变化时，同步 'project_manager' 角色。
    逻辑同 sync_project_member_role。
    """
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return

    if reverse:
        pass
    else:
        project = instance
        scope = f"project:{project.id}"
        manager_role = Role.objects.filter(code='project_manager').first()
        
        if not manager_role:
            return

        if action == 'post_add':
            for user_id in pk_set:
                user = User.objects.get(pk=user_id)
                RBACService.assign_role(user, manager_role, scope)
                
        elif action == 'post_remove':
            for user_id in pk_set:
                user = User.objects.get(pk=user_id)
                RBACService.remove_role(user, manager_role, scope)

        elif action == 'post_clear':
            UserRole.objects.filter(role=manager_role, scope=scope).delete()
