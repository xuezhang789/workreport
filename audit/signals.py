from django.db.models.signals import pre_save, post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.forms.models import model_to_dict
from audit.models import AuditLog
from audit.middleware import get_current_user
from projects.models import Project, ProjectAttachment
from tasks.models import Task, TaskAttachment
from django.contrib.auth.models import User

def get_field_verbose_name(model, field_name):
    try:
        return str(model._meta.get_field(field_name).verbose_name)
    except:
        return field_name

@receiver(pre_save, sender=Project)
@receiver(pre_save, sender=Task)
def capture_old_state(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            # We use model_to_dict but we need to handle special fields if any
            instance._old_state = model_to_dict(old_instance)
        except sender.DoesNotExist:
            instance._old_state = {}
    else:
        instance._old_state = {}

from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

@receiver(post_save, sender=Project)
@receiver(post_save, sender=Task)
def log_model_changes(sender, instance, created, **kwargs):
    user = get_current_user()
    # print(f"DEBUG: Signal triggered for {sender.__name__} {instance.pk} User: {user}")
    
    # If no user in thread local (e.g. management command), we skip or use system
    if not user and not created: 
        pass

    action = 'create' if created else 'update'
    diff = {}
    
    if not created:
        # ... (same logic for calculating diff) ...
        old_state = getattr(instance, '_old_state', {})
        new_state = model_to_dict(instance)
        
        ignored_fields = [
            'updated_at', 'created_at', 'last_login', 'password', 
            'overdue_notified_at', 'amber_notified_at', 'red_notified_at',
            'id'
        ]
        
        for field, new_val in new_state.items():
            if field in ignored_fields: continue
            
            old_val = old_state.get(field)
            
            c_old = '' if old_val is None else old_val
            c_new = '' if new_val is None else new_val
            
            if old_val != new_val:
                if c_old == c_new: continue
                
                v_name = get_field_verbose_name(sender, field)
                old_display = old_val
                new_display = new_val
                
                field_obj = sender._meta.get_field(field)

                if field_obj.choices:
                    choices_dict = dict(field_obj.choices)
                    old_display = choices_dict.get(old_val, old_val)
                    new_display = choices_dict.get(new_val, new_val)
                elif field_obj.is_relation and field_obj.many_to_one:
                    related_model = field_obj.related_model
                    def get_obj_str(model, pk):
                        if not pk: return None
                        try:
                            obj = model.objects.get(pk=pk)
                            if isinstance(obj, User):
                                return obj.get_full_name() or obj.username
                            return str(obj)
                        except model.DoesNotExist:
                            return f"Deleted {model._meta.verbose_name} ({pk})"
                        except:
                            return str(pk)
                    if old_val: old_display = get_obj_str(related_model, old_val)
                    if new_val: new_display = get_obj_str(related_model, new_val)
                else:
                    if hasattr(old_display, 'isoformat'): old_display = old_display.isoformat()
                    if isinstance(old_display, Decimal): old_display = str(old_display)
                    
                    if hasattr(new_display, 'isoformat'): new_display = new_display.isoformat()
                    if isinstance(new_display, Decimal): new_display = str(new_display)

                diff[field] = {
                    'verbose_name': v_name,
                    'old': old_display,
                    'new': new_display
                }

    if diff or created:
        operator_name = user.get_full_name() or user.username if user else 'System'
        
        project = None
        task = None
        if sender == Project:
            project = instance
        elif sender == Task:
            task = instance
            project = instance.project

        # 优化：幂等性检查 (去抖动)
        # 防止在 5 秒内为同一动作/用户/目标创建重复日志
        # 这处理了快速双击或重复信号触发
        cutoff = timezone.now() - timedelta(seconds=5)
        details = {'diff': diff}
        
        exists = AuditLog.objects.filter(
            target_type=sender.__name__,
            target_id=str(instance.pk),
            action=action,
            user=user if user else None,
            created_at__gte=cutoff
        ).first()
        
        # 如果存在，检查详情是否实际上相同
        # 注意：Python 中的 JSON 比较是安全的（字典顺序不影响相等性）
        if exists and exists.details == details:
            return # 跳过重复项

        AuditLog.objects.create(
            user=user if user else None,
            operator_name=operator_name,
            action=action,
            target_type=sender.__name__,
            target_id=str(instance.pk),
            target_label=str(instance),
            details=details,
            project=project,
            task=task
        )

# M2M 跟踪
@receiver(m2m_changed, sender=Project.members.through)
@receiver(m2m_changed, sender=Project.managers.through)
@receiver(m2m_changed, sender=Task.collaborators.through)
def log_m2m_changes(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action not in ["post_add", "post_remove", "post_clear"]: return
    
    user = get_current_user()
    # M2M 变更通常发生在用户可用的视图中
    
    field_name = ''
    if sender == Project.members.through: field_name = 'members'
    elif sender == Project.managers.through: field_name = 'managers'
    elif sender == Task.collaborators.through: field_name = 'collaborators'
    
    if not field_name: return
    
    verb = 'Added' if 'add' in action else 'Removed' if 'remove' in action else 'Cleared'
    
    names = []
    if pk_set:
        for obj in model.objects.filter(pk__in=pk_set):
            if hasattr(obj, 'get_full_name'):
                names.append(obj.get_full_name() or obj.username)
            else:
                names.append(str(obj))
    
    # 正确识别实例。对于反向 M2M（例如 user.project_set），实例是 User。
    # 但这里 sender 是 Project.members.through。
    # 如果动作是正向 (project.members.add(user))，实例是 Project，模型是 User。
    # 如果动作是反向 (user.project_memberships.add(project))，实例是 User，模型是 Project。
    
    project = None
    task = None
    target_obj = None
    
    if isinstance(instance, Project):
        project = instance
        target_obj = instance
    elif isinstance(instance, Task):
        task = instance
        project = instance.project
        target_obj = instance
    elif isinstance(instance, User):
        # 反向关系变更。我们需要为涉及的每个项目/任务记录日志。
        # 但 pk_set 包含项目/任务 ID。
        # 这很棘手，因为我们要针对项目/任务记录，而不是针对用户。
        # 我们应该遍历 pk_set 中的目标对象。
        pass

    # 如果是反向 M2M（用户侧），我们需要以不同方式处理或跳过？
    # 通常我们希望在项目/任务上记录日志。
    # 如果我做 user.project_memberships.add(p1)，instance=user，model=Project，pk_set={p1.id}
    
    if isinstance(instance, User):
        # 交换逻辑：我们要为 pk_set 中的每个项目/任务创建日志
        targets = model.objects.filter(pk__in=pk_set)
        for target in targets:
            # 递归调用或手动创建？手动创建更安全以避免无限循环
            # 确定目标侧的字段名称
            if model == Project and sender == Project.members.through:
                t_field = 'members'
            elif model == Project and sender == Project.managers.through:
                t_field = 'managers'
            elif model == Task and sender == Task.collaborators.through:
                t_field = 'collaborators'
            else:
                continue
                
            t_diff = {
                t_field: {
                    'verbose_name': get_field_verbose_name(target.__class__, t_field),
                    'action': verb,
                    'values': [instance.get_full_name() or instance.username]
                }
            }
            
            p = target if isinstance(target, Project) else target.project
            t = target if isinstance(target, Task) else None
            
            AuditLog.objects.create(
                user=user if user else None,
                operator_name=user.get_full_name() or user.username if user else 'System',
                action='update',
                target_type=target.__class__.__name__,
                target_id=str(target.pk),
                target_label=str(target),
                details={'diff': t_diff},
                project=p,
                task=t
            )
        return

    # Normal forward case (Project.members.add(user))
    diff = {
        field_name: {
            'verbose_name': get_field_verbose_name(instance.__class__, field_name),
            'action': verb,
            'values': names
        }
    }
    
    AuditLog.objects.create(
        user=user if user else None,
        operator_name=user.get_full_name() or user.username if user else 'System',
        action='update',
        target_type=instance.__class__.__name__,
        target_id=str(instance.pk),
        target_label=str(instance),
        details={'diff': diff},
        project=project,
        task=task
    )

# Attachments
@receiver(post_save, sender=ProjectAttachment)
@receiver(post_save, sender=TaskAttachment)
def log_attachment_upload(sender, instance, created, **kwargs):
    user = get_current_user()
    # Fallback to instance user field if thread local is empty (e.g. api upload)
    if not user:
        if hasattr(instance, 'uploaded_by'): user = instance.uploaded_by
        elif hasattr(instance, 'user'): user = instance.user
            
    target = instance.project if hasattr(instance, 'project') else instance.task
    target_type = target.__class__.__name__
    
    filename = getattr(instance, 'original_filename', None) or (instance.file.name if instance.file else 'unknown')
    project = target if isinstance(target, Project) else target.project
    task = target if isinstance(target, Task) else None
    
    operator_name = user.get_full_name() or user.username if user else 'System'

    if created:
        AuditLog.objects.create(
            user=user,
            operator_name=operator_name,
            action='upload',
            target_type=target_type,
            target_id=str(target.pk),
            target_label=str(target),
            details={'filename': filename, 'size': instance.file.size if instance.file else 0},
            project=project,
            task=task
        )
    else:
        # Check for updates (Rename or File Replace)
        # Note: 'original_filename' might not be available on TaskAttachment depending on model
        # ProjectAttachment has 'original_filename', TaskAttachment? Let's check model.
        # TaskAttachment usually just has 'file'.
        # We need to rely on 'file' field change or 'original_filename' if exists.
        
        # Since we don't have old instance here easily without pre_save signal capturing it,
        # we might need to rely on what changed.
        # But 'update_fields' in kwargs might be None if save() called without it.
        
        # Let's check if we can get old state.
        # We didn't register pre_save for Attachments to capture old state in this file.
        # We should add pre_save for Attachments if we want precise diff.
        pass

@receiver(pre_save, sender=ProjectAttachment)
@receiver(pre_save, sender=TaskAttachment)
def capture_attachment_old_state(sender, instance, **kwargs):
    if instance.pk:
        try:
            old = sender.objects.get(pk=instance.pk)
            instance._old_file = old.file.name if old.file else None
            instance._old_name = getattr(old, 'original_filename', None)
        except sender.DoesNotExist:
            pass

@receiver(post_save, sender=ProjectAttachment)
@receiver(post_save, sender=TaskAttachment)
def log_attachment_update(sender, instance, created, **kwargs):
    if created: return # Handled by log_attachment_upload (merged logic below)
    
    user = get_current_user()
    if not user:
        if hasattr(instance, 'uploaded_by'): user = instance.uploaded_by
        elif hasattr(instance, 'user'): user = instance.user

    target = instance.project if hasattr(instance, 'project') else instance.task
    target_type = target.__class__.__name__
    project = target if isinstance(target, Project) else target.project
    task = target if isinstance(target, Task) else None
    operator_name = user.get_full_name() or user.username if user else 'System'

    current_file = instance.file.name if instance.file else None
    current_name = getattr(instance, 'original_filename', None)
    
    old_file = getattr(instance, '_old_file', None)
    old_name = getattr(instance, '_old_name', None)
    
    actions = []
    details = {}
    
    # Check Rename
    if old_name and current_name and old_name != current_name:
        actions.append('rename')
        details['rename'] = {'old': old_name, 'new': current_name}
        
    # Check File Update (Version)
    if old_file and current_file and old_file != current_file:
        actions.append('update_file')
        details['file_update'] = {'old_size': 0, 'new_size': instance.file.size} # Size tracking hard without old obj
        
    if actions:
        AuditLog.objects.create(
            user=user,
            operator_name=operator_name,
            action='update', # Generic update, details specify
            target_type=target_type,
            target_id=str(target.pk),
            target_label=str(target),
            details={'attachment_actions': actions, 'changes': details, 'filename': current_name or current_file},
            project=project,
            task=task
        )

@receiver(post_delete, sender=ProjectAttachment)
@receiver(post_delete, sender=TaskAttachment)
def log_attachment_delete(sender, instance, **kwargs):
    user = get_current_user()
    
    target = instance.project if hasattr(instance, 'project') else instance.task
    target_type = target.__class__.__name__
    filename = getattr(instance, 'original_filename', None) or (instance.file.name if instance.file else 'unknown')
    
    project = target if isinstance(target, Project) else target.project
    task = target if isinstance(target, Task) else None

    AuditLog.objects.create(
        user=user,
        operator_name=user.get_full_name() or user.username if user else 'System',
        action='delete', 
        target_type=target_type,
        target_id=str(target.pk),
        target_label=str(target),
        details={'filename': filename, 'type': 'attachment'},
        project=project,
        task=task
    )
