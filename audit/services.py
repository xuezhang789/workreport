from django.db.models import Q
from audit.models import AuditLog
from django.utils.dateparse import parse_date

class AuditLogService:
    @staticmethod
    def get_history(target_obj, filters=None):
        """
        Get audit history QuerySet for a specific target object (Project or Task).
        Supports filtering by user, date, action, and specific field changes via DB lookups.
        Returns a QuerySet (lazy), not a list.
        """
        filters = filters or {}
        
        target_type = target_obj.__class__.__name__
        target_id = str(target_obj.pk)
        
        qs = AuditLog.objects.filter(target_type=target_type, target_id=target_id).select_related('user')
        
        # Filter by User (Operator)
        if filters.get('user_id'):
            qs = qs.filter(user_id=filters.get('user_id'))
            
        # Filter by Date Range
        if filters.get('start_date'):
            start = parse_date(filters.get('start_date'))
            if start:
                qs = qs.filter(created_at__date__gte=start)
                
        if filters.get('end_date'):
            end = parse_date(filters.get('end_date'))
            if end:
                qs = qs.filter(created_at__date__lte=end)
                
        # Filter by Action Type
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
        
        # Filter by Field Name (DB Level Optimization)
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
                # Field change: details -> diff -> field_name exists
                qs = qs.filter(details__diff__has_key=f_name)

        return qs.order_by('-created_at')

    @staticmethod
    def format_log_entry(log, field_filter=None):
        """
        Process a single AuditLog instance into a display-friendly dictionary.
        Args:
            log: AuditLog instance
            field_filter: If provided, only return items matching this field name.
        """
        entry = {
            'id': log.id,
            'timestamp': log.created_at,
            'user': log.user,
            'operator_name': log.operator_name,
            'action': log.action,
            'items': []
        }
        
        # 1. Field Changes (Diff)
        if log.details and 'diff' in log.details:
            diff = log.details['diff']
            
            # Apply field filter if strict filtering is required
            if field_filter and field_filter not in ['attachment', 'comment']:
                if field_filter in diff:
                    diff = {field_filter: diff[field_filter]}
                else:
                    diff = {} # Should not happen if DB filtered correctly, but safe fallback

            for field, change in diff.items():
                if isinstance(change, dict):
                    # Handle M2M changes
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
                        # Standard field change
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
                    # Fallback for old logs or malformed data
                    entry['items'].append({
                        'type': 'field',
                        'field': field,
                        'field_key': field,
                        'old': str(change),
                        'new': None,
                        'action': 'changed'
                    })

        # 2. Attachments
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

        # 3. Comments
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

        # 4. Create/General (Lifecycle)
        # Only show lifecycle if no filter or specific filter matches?
        # Usually lifecycle is separate. If filtering by field 'status', do we show 'Created'?
        # Probably not.
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
