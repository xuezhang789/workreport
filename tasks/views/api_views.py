from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from tasks.models import Task
from reports.utils import get_accessible_projects

@login_required
def api_task_detail(request, pk: int):
    """用于编辑表单的获取任务详情的 API。"""
    task = get_object_or_404(Task, pk=pk)
    
    # 权限检查 (重用 admin_task_edit 的逻辑)
    can_see = get_accessible_projects(request.user).filter(id=task.project.id).exists() or \
              task.user == request.user or \
              task.collaborators.filter(pk=request.user.pk).exists()
              
    if not can_see:
        return JsonResponse({'error': 'Not Found'}, status=404)
        
    return JsonResponse({
        'id': task.id,
        'title': task.title,
        'url': task.url,
        'content': task.content,
        'project_id': task.project_id,
        'user_id': task.user_id,
        'category': task.category,
        'status': task.status,
        'priority': task.priority,
        'due_at': task.due_at.isoformat() if task.due_at else '',
        'collaborator_ids': list(task.collaborators.values_list('id', flat=True)),
    })
