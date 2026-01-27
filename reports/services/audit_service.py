import json
from django.forms.models import model_to_dict
from reports.models import AuditLog

class AuditService:
    @staticmethod
    def log_change(user, action, instance, old_instance=None, ip=None, remarks='', path='', method='', changes=None, result='success'):
        """
        Log a change to the audit log.
        """
        target_type = instance.__class__.__name__
        target_id = str(instance.pk)
        target_label = str(instance)[:255]
        
        operator_name = user.get_full_name() or user.username if user and user.is_authenticated else 'System/Anonymous'
        
        # Determine Project & Task Context
        project = None
        task = None
        
        if target_type == 'Task':
            task = instance
            project = instance.project
        elif target_type == 'Project':
            project = instance
        elif target_type == 'TaskComment':
            task = instance.task
            project = instance.task.project
        elif target_type == 'TaskAttachment':
            task = instance.task
            project = instance.task.project
        elif hasattr(instance, 'project') and instance.project and hasattr(instance.project, 'pk'): # Check if project is a FK model instance
             # Generic fallback for models with 'project' FK
             project = instance.project
             
        # DailyReport Special Handling
        # DailyReport has M2M 'projects'. We can't easily assign a single project unless we pick one.
        # But log_change is usually for one instance. 
        # For now, we leave project=None for DailyReport unless we want to log multiple entries (too complex here).

        details = {}
        if changes is None:
            if action == 'update' and old_instance:
                details['diff'] = AuditService._calculate_diff(old_instance, instance)
            elif action == 'create':
                details['diff'] = {'_all': 'Created'}
        else:
            details['diff'] = changes
            
        if path or method:
            details['context'] = {'path': path, 'method': method}
            
        AuditLog.objects.create(
            user=user if user and user.is_authenticated else None,
            operator_name=operator_name,
            action=action,
            result=result,
            target_type=target_type,
            target_id=target_id,
            target_label=target_label,
            details=details,
            project=project,
            task=task,
            ip=ip,
            summary=remarks,
        )

    @staticmethod
    def _calculate_diff(old_instance, new_instance):
        diff = {}
        # Get fields
        for field in new_instance._meta.fields:
            field_name = field.name
            
            try:
                old_val = getattr(old_instance, field_name)
                new_val = getattr(new_instance, field_name)
                
                # Convert to string or comparable format if needed
                if old_val != new_val:
                    diff[field_name] = {
                        'old': str(old_val),
                        'new': str(new_val)
                    }
            except Exception:
                continue
                
        return diff
