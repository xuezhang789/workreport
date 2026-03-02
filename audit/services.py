from django.db.models import Q
from django.apps import apps
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
        # 稳健性修复：始终包含关键关联以避免 target_type 逻辑脆弱时出现问题
        related_fields = ['user', 'project', 'task']

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
            'changes': {},
            'summary_html': '' 
        }
        
        # 5. 仓库 (Repository)
        should_show_repos = not field_filter or field_filter == 'repository'
        if should_show_repos and log.target_type == 'Project':
            repo_name = None
            action_verb = None
            
            # 新格式：details={'repository': {'name': '...'}}
            if log.details and 'repository' in log.details:
                repo_name = log.details['repository'].get('name')
                if log.action == 'create':
                    action_verb = 'Added'
                elif log.action == 'delete':
                    action_verb = 'Removed'
            
            # 传统格式支持（来自之前的尝试）
            elif 'repository' in log.summary:
                try:
                    if 'Added repository' in log.summary:
                         repo_name = log.summary.split('Added repository', 1)[1].strip()
                         action_verb = 'Added'
                    elif 'Removed repository' in log.summary:
                         repo_name = log.summary.split('Removed repository', 1)[1].strip()
                         action_verb = 'Removed'
                    elif 'for project' in log.summary:
                        repo_name = log.summary.split('repository', 1)[1].split('for project')[0].strip()
                        action_verb = 'Added' if log.action == 'create' else 'Removed'
                    elif 'from project' in log.summary:
                        repo_name = log.summary.split('repository', 1)[1].split('from project')[0].strip()
                        action_verb = 'Removed'
                except (IndexError, ValueError):
                    pass
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Failed to parse audit log summary for repository info: {e}")

            if repo_name and action_verb:
                if action_verb == 'Added':
                    entry['changes']['代码仓库'] = [None, repo_name]
                else:
                    entry['changes']['代码仓库'] = [repo_name, None]

        # 1. 字段变更 (Diff)
        if log.details and 'diff' in log.details:
            diff = log.details['diff']
            
            # 如果需要严格过滤，应用字段过滤器
            if field_filter and field_filter not in ['attachment', 'comment']:
                if field_filter in diff:
                    diff = {field_filter: diff[field_filter]}
                else:
                    diff = {} 

            # 获取模型类以查找 verbose_name
            ModelClass = None
            try:
                # 尝试根据 target_type 获取模型
                # 常用模型映射
                app_map = {
                    'Project': 'projects',
                    'Task': 'tasks',
                    'User': 'auth',
                    'Profile': 'core',
                    'ProjectAttachment': 'projects',
                    'TaskAttachment': 'tasks',
                }
                app_label = app_map.get(log.target_type)
                if app_label:
                    ModelClass = apps.get_model(app_label, log.target_type)
            except Exception:
                pass

            for field, change in diff.items():
                val_list = None
                # Check if change is list [old, new] (New format) or dict (Old format)
                if isinstance(change, list) and len(change) == 2:
                    val_list = change
                elif isinstance(change, dict):
                    # Handle old format or M2M dict
                    if 'old' in change and 'new' in change:
                         val_list = [change['old'], change['new']]
                    elif 'action' in change and 'values' in change:
                         # M2M
                         action_verb = change.get('action')
                         values = change.get('values', [])
                         val_str = ", ".join(values)
                         if action_verb == 'Added':
                             val_list = [None, val_str]
                         else:
                             val_list = [val_str, None]
                    elif 'verbose_name' in change:
                         # Old explicit format
                         val_list = [change.get('old'), change.get('new')]
                
                if val_list:
                    # Resolve verbose name
                    display_field = field
                    if ModelClass:
                        try:
                            f = ModelClass._meta.get_field(field)
                            display_field = str(f.verbose_name)
                        except Exception:
                            # 可能是 M2M 字段或不存在的字段
                            pass
                    
                    # 特殊字段处理
                    if field == 'members': display_field = '项目成员'
                    if field == 'managers': display_field = '项目经理'
                    if field == 'collaborators': display_field = '协作人'

                    entry['changes'][display_field] = val_list

        # 2. 附件
        should_show_attachments = not field_filter or field_filter == 'attachment'
        if should_show_attachments:
            if log.action in ['upload', 'delete'] or (log.details and 'attachment_actions' in log.details):
                filename = log.details.get('filename', 'Unknown File')
                if log.action == 'upload':
                    entry['changes']['附件'] = [None, filename]
                elif log.action == 'delete':
                    entry['changes']['附件'] = [filename, None]
                elif 'attachment_actions' in log.details:
                    actions = log.details['attachment_actions']
                    for act in actions:
                        if act == 'rename':
                            changes = log.details.get('changes', {}).get('rename', {})
                            old_name = changes.get('old', filename)
                            new_name = changes.get('new', filename)
                            entry['changes']['附件 (重命名)'] = [old_name, new_name]
                        elif act == 'update_file':
                            entry['changes']['附件 (更新内容)'] = [f"{filename} (v1)", f"{filename} (v2)"]

        # 3. 评论
        should_show_comments = not field_filter or field_filter == 'comment'
        if should_show_comments and 'comment' in log.summary:
             entry['changes']['评论'] = [None, 'New Comment']

        # 4. 创建/通用
        if not field_filter and log.action == 'create' and not entry['changes']:
             entry['changes']['项目/任务'] = [None, 'Created']
        
        # Populate items for backward compatibility if needed, but currently template uses changes
        # Return entry only if it has changes or we want to show it anyway
        return entry if entry['changes'] else None
