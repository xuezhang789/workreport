
# In reports/views.py

@login_required
def api_project_detail(request, pk: int):
    """API to get project details for editing form."""
    project = get_object_or_404(Project, pk=pk)
    if not can_manage_project(request.user, project):
        return JsonResponse({'error': 'Forbidden'}, status=403)
        
    return JsonResponse({
        'id': project.id,
        'name': project.name,
        'code': project.code,
        'description': project.description,
        'start_date': project.start_date.isoformat() if project.start_date else '',
        'end_date': project.end_date.isoformat() if project.end_date else '',
        'sla_hours': project.sla_hours,
        'is_active': project.is_active,
        'owner_id': project.owner_id,
        'manager_ids': list(project.managers.values_list('id', flat=True)),
        'member_ids': list(project.members.values_list('id', flat=True)),
    })

@login_required
def api_task_detail(request, pk: int):
    """API to get task details for editing form."""
    task = get_object_or_404(Task, pk=pk)
    
    # Permission check (reuse logic from admin_task_edit)
    can_see = request.user.is_superuser or \
              get_accessible_projects(request.user).filter(id=task.project.id).exists() or \
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
        'status': task.status,
        'priority': task.priority,
        'due_at': task.due_at.isoformat() if task.due_at else '',
        'collaborator_ids': list(task.collaborators.values_list('id', flat=True)),
    })
