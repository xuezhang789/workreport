
from django.db.models.signals import post_delete, post_save, m2m_changed, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import ProjectAttachment, Project
from core.models import Role, UserRole
from core.services.rbac import RBACService
from reports.services.notification_service import send_notification
from reports.middleware import get_current_user

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
    Post-save 信号：当项目所有者变更时，同步 'project_owner' 角色并发送通知。
    """
    scope = f"project:{instance.id}"
    owner_role = Role.objects.filter(code='project_owner').first()
    current_user = get_current_user()
    
    # 场景1：新建项目
    if created and instance.owner:
        if owner_role:
            RBACService.assign_role(instance.owner, owner_role, scope)
        
        # 通知新任命的负责人
        send_notification(
            user=instance.owner,
            title="项目任命 / Project Assignment",
            message=f"您已被任命为项目 {instance.name} ({instance.code}) 的负责人。",
            notification_type='project_assignment',
            priority='high',
            data={'project_id': instance.id, 'action_url': f'/projects/{instance.id}/'}
        )
        return

    # 场景2：所有者变更
    old_owner = getattr(instance, '_old_owner', None)
    new_owner = instance.owner

    if old_owner and old_owner != new_owner:
        if owner_role:
            RBACService.remove_role(old_owner, owner_role, scope)
        
        # 通知旧负责人
        if old_owner != current_user:
            send_notification(
                user=old_owner,
                title="负责人变更 / Project Owner Change",
                message=f"您不再担任项目 {instance.name} 的负责人。",
                notification_type='project_assignment',
                priority='high',
                data={'project_id': instance.id, 'action_url': f'/projects/{instance.id}/'}
            )
    
    if new_owner and new_owner != old_owner:
        if owner_role:
            RBACService.assign_role(new_owner, owner_role, scope)
        
        # 通知新负责人
        if new_owner != current_user:
            send_notification(
                user=new_owner,
                title="项目任命 / Project Assignment",
                message=f"您已被任命为项目 {instance.name} ({instance.code}) 的负责人。",
                notification_type='project_assignment',
                priority='high',
                data={'project_id': instance.id, 'action_url': f'/projects/{instance.id}/'}
            )

@receiver(m2m_changed, sender=Project.members.through)
def sync_project_member_role(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    M2M 变更信号：当项目成员列表发生变化时，同步 'project_member' 角色并发送通知。
    """
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return

    if reverse:
        pass
    else:
        project = instance
        scope = f"project:{project.id}"
        member_role = Role.objects.filter(code='project_member').first()
        current_user = get_current_user()

        if action == 'post_add':
            users_added = []
            for user_id in pk_set:
                try:
                    user = User.objects.get(pk=user_id)
                    users_added.append(user)
                    if member_role:
                        RBACService.assign_role(user, member_role, scope)
                    
                    # 通知成员
                    if user != current_user:
                        send_notification(
                            user=user,
                            title="加入项目 / Joined Project",
                            message=f"您已被添加到项目 {project.name} 成员列表中。",
                            notification_type='project_member_change',
                            priority='normal',
                            data={'project_id': project.id, 'action_url': f'/projects/{project.id}/'}
                        )
                except User.DoesNotExist:
                    continue
            
            # 通知项目负责人
            if project.owner and project.owner != current_user and users_added:
                names = ", ".join([u.get_full_name() or u.username for u in users_added])
                send_notification(
                    user=project.owner,
                    title="成员加入 / Member Added",
                    message=f"{names} 已加入项目 {project.name}。",
                    notification_type='project_member_change',
                    priority='normal',
                    data={'project_id': project.id, 'action_url': f'/projects/{project.id}/members/'}
                )

        elif action == 'post_remove':
            users_removed = []
            for user_id in pk_set:
                try:
                    user = User.objects.get(pk=user_id)
                    users_removed.append(user)
                    if member_role:
                        RBACService.remove_role(user, member_role, scope)
                    
                    # 通知成员
                    if user != current_user:
                        send_notification(
                            user=user,
                            title="移出项目 / Removed from Project",
                            message=f"您已被移出项目 {project.name}。",
                            notification_type='project_member_change',
                            priority='normal',
                            data={'project_id': project.id}
                        )
                except User.DoesNotExist:
                    continue
            
            # 通知项目负责人
            if project.owner and project.owner != current_user and users_removed:
                names = ", ".join([u.get_full_name() or u.username for u in users_removed])
                send_notification(
                    user=project.owner,
                    title="成员移除 / Member Removed",
                    message=f"{names} 已被移出项目 {project.name}。",
                    notification_type='project_member_change',
                    priority='normal',
                    data={'project_id': project.id, 'action_url': f'/projects/{project.id}/members/'}
                )

        elif action == 'post_clear':
            # 清空该项目下所有的成员角色关联
            UserRole.objects.filter(role=member_role, scope=scope).delete()

@receiver(m2m_changed, sender=Project.managers.through)
def sync_project_manager_role(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    M2M 变更信号：当项目管理员列表发生变化时，同步 'project_manager' 角色并发送通知。
    """
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return

    if reverse:
        pass
    else:
        project = instance
        scope = f"project:{project.id}"
        manager_role = Role.objects.filter(code='project_manager').first()
        current_user = get_current_user()
        
        if action == 'post_add':
            users_added = []
            for user_id in pk_set:
                try:
                    user = User.objects.get(pk=user_id)
                    users_added.append(user)
                    if manager_role:
                        RBACService.assign_role(user, manager_role, scope)
                    
                    # 通知管理员
                    if user != current_user:
                        send_notification(
                            user=user,
                            title="任命管理员 / Manager Assignment",
                            message=f"您已被任命为项目 {project.name} 的管理员。",
                            notification_type='project_manager_change',
                            priority='high',
                            data={'project_id': project.id, 'action_url': f'/projects/{project.id}/'}
                        )
                except User.DoesNotExist:
                    continue
            
            # 通知项目负责人
            if project.owner and project.owner != current_user and users_added:
                names = ", ".join([u.get_full_name() or u.username for u in users_added])
                send_notification(
                    user=project.owner,
                    title="管理员添加 / Manager Added",
                    message=f"{names} 已被添加为项目 {project.name} 的管理员。",
                    notification_type='project_manager_change',
                    priority='normal',
                    data={'project_id': project.id, 'action_url': f'/projects/{project.id}/'}
                )
                
        elif action == 'post_remove':
            users_removed = []
            for user_id in pk_set:
                try:
                    user = User.objects.get(pk=user_id)
                    users_removed.append(user)
                    if manager_role:
                        RBACService.remove_role(user, manager_role, scope)
                    
                    # 通知管理员
                    if user != current_user:
                        send_notification(
                            user=user,
                            title="移除管理员 / Manager Removal",
                            message=f"您已被移除项目 {project.name} 的管理员身份。",
                            notification_type='project_manager_change',
                            priority='high',
                            data={'project_id': project.id, 'action_url': f'/projects/{project.id}/'}
                        )
                except User.DoesNotExist:
                    continue
            
            # 通知项目负责人
            if project.owner and project.owner != current_user and users_removed:
                names = ", ".join([u.get_full_name() or u.username for u in users_removed])
                send_notification(
                    user=project.owner,
                    title="管理员移除 / Manager Removed",
                    message=f"{names} 已被移除项目 {project.name} 的管理员身份。",
                    notification_type='project_manager_change',
                    priority='normal',
                    data={'project_id': project.id, 'action_url': f'/projects/{project.id}/'}
                )

        elif action == 'post_clear':
            UserRole.objects.filter(role=manager_role, scope=scope).delete()
