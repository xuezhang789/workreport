from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import StreamingHttpResponse, Http404
from django.utils import timezone
from projects.models import Project
from audit.services import AuditLogService
from reports.utils import get_accessible_projects
from core.utils import _stream_csv

@login_required
def project_history_export(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    
    # Permission check
    # 权限检查
    if not request.user.is_superuser:
        accessible = get_accessible_projects(request.user)
        if not accessible.filter(id=project.id).exists():
             raise Http404

    # Filters (reuse logic from project_history)
    # 过滤器（重用项目历史记录的逻辑）
    filters = {
        'user_id': request.GET.get('user'),
        'start_date': request.GET.get('start_date'),
        'end_date': request.GET.get('end_date'),
        'action_type': request.GET.get('action_type'),
        'field_name': request.GET.get('field'),
    }

    timeline = AuditLogService.get_history(project, filters)
    
    rows = []
    for entry in timeline:
        timestamp = timezone.localtime(entry['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
        operator = entry['operator_name']
        
        for item in entry['items']:
            field = item.get('field', 'Unknown')
            old_val = item.get('old', '')
            new_val = item.get('new', '')
            desc = item.get('description', '')
            item_type = item.get('type', 'general')
            
            # Format: Timestamp, Operator, Type, Field, Old, New, Description
            # 格式：时间戳，操作人，类型，字段，旧值，新值，描述
            rows.append([
                timestamp,
                operator,
                item_type,
                field,
                old_val,
                new_val,
                desc
            ])

    header = ["时间 / Time", "操作人 / Operator", "类型 / Type", "字段 / Field", "旧值 / Old", "新值 / New", "描述 / Description"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="project_{project.code}_history.csv"'
    return response
