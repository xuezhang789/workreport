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

        # 关键词搜索
        if filters.get('q'):
            query = filters.get('q')
            qs = qs.filter(
                Q(summary__icontains=query) | 
                Q(details__icontains=query) |
                Q(operator_name__icontains=query)
            )

        # 性能优化：根据目标对象类型减少冗余的关联查询
        # Performance Optimization: Reduce redundant joins based on target type
        related_fields = ['user']
        if target_type != 'Project':
            related_fields.append('project')
        if target_type != 'Task':
            related_fields.append('task')

        return qs.select_related(*related_fields).order_by('-created_at')

    @staticmethod
    def format_log_entry(log, field_filter=None):
        """
        将单个 AuditLog 实例处理为显示友好的字典。
        """
        entry = {
            'id': log.id,
            'timestamp': log.created_at,
            'user': log.user,
            'operator_name': log.operator_name,
            'action': log.action,
            'items': [],
            'summary_html': '' # For simplified display
        }
        
        # Helper to add item
        def add_item(type_, field, old, new, action, desc=None):
            entry['items'].append({
                'type': type_,
                'field': field,
                'action': action,
                'old': old,
                'new': new,
                'description': desc or f"{action} {field}"
            })

        # 1. 字段变更 (Diff)
        if log.details and 'diff' in log.details:
            diff = log.details['diff']
            
            # 如果需要严格过滤，应用字段过滤器
            if field_filter and field_filter not in ['attachment', 'comment']:
                if field_filter in diff:
                    diff = {field_filter: diff[field_filter]}
                else:
                    diff = {} 

            for field, change in diff.items():
                if isinstance(change, dict):
                    # 处理 M2M 变更
                    if 'action' in change and 'values' in change:
                        action_verb = change.get('action')
                        values = change.get('values', [])
                        # Use badge style HTML for values if possible, but raw string for now
                        values_str = ", ".join(values)
                        
                        add_item('field', change.get('verbose_name', field), 
                                 values_str if action_verb == 'Removed' else None,
                                 values_str if action_verb == 'Added' else None,
                                 action_verb)
                    else:
                        # 标准字段变更
                        old_val = change.get('old')
                        new_val = change.get('new')
                        add_item('field', change.get('verbose_name', field),
                                 str(old_val) if old_val is not None else None,
                                 str(new_val) if new_val is not None else None,
                                 'Changed')
                else:
                    # 兼容旧日志
                    add_item('field', field, str(change), None, 'Changed')

        # 2. 附件
        should_show_attachments = not field_filter or field_filter == 'attachment'
        if should_show_attachments:
            if log.action in ['upload', 'delete'] or (log.details and 'attachment_actions' in log.details):
                filename = log.details.get('filename', 'Unknown File')
                if log.action == 'upload':
                    add_item('attachment', '附件 / Attachment', None, filename, 'Uploaded', f"Uploaded {filename}")
                elif log.action == 'delete':
                    add_item('attachment', '附件 / Attachment', filename, None, 'Deleted', f"Deleted {filename}")
                elif 'attachment_actions' in log.details:
                    actions = log.details['attachment_actions']
                    for act in actions:
                        if act == 'rename':
                            changes = log.details.get('changes', {}).get('rename', {})
                            old_name = changes.get('old', filename)
                            new_name = changes.get('new', filename)
                            add_item('attachment', '附件 (重命名)', old_name, new_name, 'Renamed', f"Renamed {old_name} to {new_name}")
                        elif act == 'update_file':
                            add_item('attachment', '附件 (更新)', f"{filename} (v1)", f"{filename} (v2)", 'Updated', f"Updated content of {filename}")

        # 3. 评论
        should_show_comments = not field_filter or field_filter == 'comment'
        if should_show_comments and 'comment' in log.summary:
            add_item('comment', '评论 / Comment', None, 'New Comment', 'Added', 'Added a comment')

        # 4. 创建/通用
        if not field_filter and log.action == 'create' and not entry['items']:
             add_item('lifecycle', '生命周期 / Lifecycle', None, 'Created', 'Created', f"Created {log.target_type}")
        
        return entry if entry['items'] else None
