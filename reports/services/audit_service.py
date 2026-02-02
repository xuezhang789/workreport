import json
from django.forms.models import model_to_dict
from reports.models import AuditLog

class AuditService:
    @staticmethod
    def log_change(user, action, instance, old_instance=None, ip=None, remarks='', path='', method='', changes=None, result='success'):
        """
        记录变更到审计日志。
        """
        target_type = instance.__class__.__name__
        target_id = str(instance.pk)
        target_label = str(instance)[:255]
        
        operator_name = user.get_full_name() or user.username if user and user.is_authenticated else 'System/Anonymous'
        
        # 确定项目和任务上下文
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
        elif hasattr(instance, 'project') and instance.project and hasattr(instance.project, 'pk'): # 检查项目是否为外键模型实例
             # 具有 'project' 外键的模型的通用回退
             project = instance.project
             
        # 日报特殊处理
        # 日报具有多对多 'projects' 字段。除非我们选择一个，否则我们无法轻松分配单个项目。
        # 但 log_change 通常用于单个实例。
        # 目前，对于日报我们保留 project=None，除非我们想记录多个条目（此处过于复杂）。

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
        # 获取字段
        for field in new_instance._meta.fields:
            field_name = field.name
            
            try:
                old_val = getattr(old_instance, field_name)
                new_val = getattr(new_instance, field_name)
                
                # 如果需要，转换为字符串或可比较的格式
                if old_val != new_val:
                    diff[field_name] = {
                        'old': str(old_val),
                        'new': str(new_val)
                    }
            except Exception:
                continue
                
        return diff
