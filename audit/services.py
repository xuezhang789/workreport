from django.db.models import Q
from audit.models import AuditLog
from django.utils.dateparse import parse_date

class AuditLogService:
    @staticmethod
    def get_history(target_obj, filters=None):
        """
        获取特定目标对象（项目或任务）的审计历史查询集。
        支持按用户、日期、动作和特定字段变更进行过滤。
        返回一个 QuerySet（惰性），而不是列表。
        """
        filters = filters or {}
        
        target_type = target_obj.__class__.__name__
        target_id = str(target_obj.pk)
        
        qs = AuditLog.objects.filter(target_type=target_type, target_id=target_id).select_related('user')
        
        # 过滤掉手动访问日志或冗余日志
        # 我们只想要数据变更或特定操作，如上传/导出
        qs = qs.exclude(target_type='AccessLog')
        
        # 按用户过滤 (操作人)
        if filters.get('user_id'):
            qs = qs.filter(user_id=filters.get('user_id'))
            
        # 按日期范围过滤
        if filters.get('start_date'):
            start = parse_date(filters.get('start_date'))
            if start:
                qs = qs.filter(created_at__date__gte=start)
                
        if filters.get('end_date'):
            end = parse_date(filters.get('end_date'))
            if end:
                qs = qs.filter(created_at__date__lte=end)
                
        # 按动作类型过滤
        action_type = filters.get('action_type')
        if action_type:
            if action_type == 'field_change':
                qs = qs.filter(action='update')
            elif action_type == 'attachment':
                qs = qs.filter(
                    Q(action__in=['upload', 'delete']) | 
                    Q(details__has_key='attachment_actions') | 
                    Q(details__type='attachment')
                )
            elif action_type == 'comment':
                 qs = qs.filter(summary__icontains='comment')
        
        # 按字段名称过滤 (数据库级优化)
        if filters.get('field_name'):
            f_name = filters.get('field_name')
            if f_name == 'attachment':
                qs = qs.filter(
                    Q(action__in=['upload', 'delete']) | 
                    Q(details__has_key='attachment_actions')
                )
            elif f_name == 'comment':
                qs = qs.filter(summary__icontains='comment')
            else:
                # 字段变更: details -> diff -> field_name 存在
                qs = qs.filter(details__diff__has_key=f_name)

        return qs.order_by('-created_at')

    @staticmethod
    def format_log_entry(log, field_filter=None):
        """
        将单个 AuditLog 实例处理为显示友好的字典。
        参数:
            log: AuditLog 实例
            field_filter: 如果提供，则仅返回匹配此字段名称的项目。
        """
        entry = {
            'id': log.id,
            'timestamp': log.created_at,
            'user': log.user,
            'operator_name': log.operator_name,
            'action': log.action,
            'items': []
        }
        
        # 1. 字段变更 (Diff)
        if log.details and 'diff' in log.details:
            diff = log.details['diff']
            
            # 如果需要严格过滤，应用字段过滤器
            if field_filter and field_filter not in ['attachment', 'comment']:
                if field_filter in diff:
                    diff = {field_filter: diff[field_filter]}
                else:
                    diff = {} # 如果数据库过滤正确，这不应发生，但作为安全回退


            for field, change in diff.items():
                if isinstance(change, dict):
                    # 处理 M2M 变更
                    if 'action' in change and 'values' in change:
                        action_verb = change.get('action')
                        values = change.get('values', [])
                        values_str = ", ".join(values)
                        
                        entry['items'].append({
                            'type': 'field',
                            'field': change.get('verbose_name', field),
                            'field_key': field,
                            'old': values_str if action_verb == 'Removed' else None,
                            'new': values_str if action_verb == 'Added' else None,
                            'action': action_verb
                        })
                    else:
                        # 标准字段变更
                        old_val = change.get('old')
                        new_val = change.get('new')
                        entry['items'].append({
                            'type': 'field',
                            'field': change.get('verbose_name', field),
                            'field_key': field,
                            'old': str(old_val) if old_val is not None else None,
                            'new': str(new_val) if new_val is not None else None,
                            'action': 'changed'
                        })
                else:
                    # 兼容旧日志或格式错误的数据
                    entry['items'].append({
                        'type': 'field',
                        'field': field,
                        'field_key': field,
                        'old': str(change),
                        'new': None,
                        'action': 'changed'
                    })

        # 2. 附件
        should_show_attachments = not field_filter or field_filter == 'attachment'
        if should_show_attachments:
            if log.action in ['upload', 'delete'] or (log.details and 'attachment_actions' in log.details):
                filename = log.details.get('filename', 'Unknown File')
                if log.action == 'upload':
                    entry['items'].append({
                        'type': 'attachment',
                        'field': '附件 / Attachment',
                        'action': 'Added',
                        'old': None,
                        'new': filename,
                        'description': f"Uploaded {filename}"
                    })
                elif log.action == 'delete':
                    entry['items'].append({
                        'type': 'attachment',
                        'field': '附件 / Attachment',
                        'action': 'Removed',
                        'old': filename,
                        'new': None,
                        'description': f"Deleted {filename}"
                    })
                elif 'attachment_actions' in log.details:
                    actions = log.details['attachment_actions']
                    for act in actions:
                        if act == 'rename':
                            changes = log.details.get('changes', {}).get('rename', {})
                            old_name = changes.get('old', filename)
                            new_name = changes.get('new', filename)
                            entry['items'].append({
                                'type': 'attachment',
                                'field': '附件 (重命名) / Attachment (Rename)',
                                'action': 'Rename',
                                'old': old_name,
                                'new': new_name,
                                'description': f"Renamed {old_name} to {new_name}"
                            })
                        elif act == 'update_file':
                            entry['items'].append({
                                'type': 'attachment',
                                'field': '附件 (更新) / Attachment (Update)',
                                'action': 'Update',
                                'old': f"{filename} (Old)",
                                'new': f"{filename} (New)",
                                'description': f"Updated content of {filename}"
                            })

        # 3. 评论
        should_show_comments = not field_filter or field_filter == 'comment'
        if should_show_comments and 'comment' in log.summary:
            entry['items'].append({
                'type': 'comment',
                'field': '评论 / Comment',
                'action': 'Added',
                'old': '',
                'new': '新评论 / New Comment',
                'description': 'Added a comment'
            })

        # 4. 创建/通用 (生命周期)
        # 仅在无过滤器或特定过滤器匹配时显示生命周期？
        # 通常生命周期是分开的。如果按字段 'status' 过滤，我们是否显示 'Created'？
        # 可能不会。
        if not field_filter and log.action == 'create' and not entry['items']:
             entry['items'].append({
                'type': 'lifecycle',
                'field': '生命周期 / Lifecycle',
                'action': 'Created',
                'old': '',
                'new': '已创建 / Created',
                'description': f"Created {log.target_type}"
            })
        
        return entry if entry['items'] else None
