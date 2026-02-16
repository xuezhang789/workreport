
from django.db.models.signals import post_delete, post_save, m2m_changed, pre_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import ProjectAttachment, Project
from core.models import Role, UserRole
from core.services.rbac import RBACService

@receiver(post_delete, sender=ProjectAttachment)
def delete_project_attachment_file(sender, instance, **kwargs):
    """
    Delete the file from storage when ProjectAttachment is deleted.
    Ensures data consistency between data and storage.
    """
    if instance.file:
        instance.file.delete(save=False)

# --- RBAC Sync Signals ---

@receiver(pre_save, sender=Project)
def track_old_owner(sender, instance, **kwargs):
    """Track the old owner before saving to handle owner changes."""
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
    Sync 'project_owner' role when project owner changes.
    """
    scope = f"project:{instance.id}"
    owner_role = Role.objects.filter(code='project_owner').first()
    
    if not owner_role:
        return

    # Handle New Project
    if created and instance.owner:
        RBACService.assign_role(instance.owner, owner_role, scope)
        return

    # Handle Owner Change
    old_owner = getattr(instance, '_old_owner', None)
    new_owner = instance.owner

    if old_owner and old_owner != new_owner:
        RBACService.remove_role(old_owner, owner_role, scope)
    
    if new_owner and new_owner != old_owner:
        RBACService.assign_role(new_owner, owner_role, scope)

@receiver(m2m_changed, sender=Project.members.through)
def sync_project_member_role(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    Sync 'project_member' role when members are added/removed.
    """
    if action not in ['post_add', 'post_remove', 'post_clear']:
        return

    # When reverse=False (Project -> User), instance is Project
    # When reverse=True (User -> Project), instance is User
    # We only handle forward direction (Project -> User) for simplicity now, 
    # or handle both. But typically we add members via Project.members.add(user).
    
    if reverse:
        # instance is User, pk_set are Project IDs
        # We need to assign role for each project in pk_set to this user
        # Not implementing reverse for now as it's less common to do user.project_memberships.add(project)
        # But for robustness we should.
        pass
    else:
        # instance is Project, pk_set are User IDs
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
            UserRole.objects.filter(role=member_role, scope=scope).delete()

@receiver(m2m_changed, sender=Project.managers.through)
def sync_project_manager_role(sender, instance, action, reverse, model, pk_set, **kwargs):
    """
    Sync 'project_manager' role when managers are added/removed.
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
