from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.db.models import Q
from django.contrib.auth import get_user_model

from work_logs.models import DailyReport
from tasks.models import Task
from projects.models import Project
from reports.utils import get_accessible_projects, get_accessible_reports, get_accessible_tasks
from audit.utils import log_action

@login_required
def global_search(request):
    q = (request.GET.get('q') or '').strip()
    scope = request.GET.get('scope', 'all')
    
    results = {
        'projects': [],
        'tasks': [],
        'reports': [],
        'users': [],
    }
    
    if q:
        # Projects
        # 项目
        if scope in ('all', 'projects'):
            accessible_projects = get_accessible_projects(request.user)
            results['projects'] = accessible_projects.filter(
                Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q)
            ).distinct()[:10]

        # Tasks
        # 任务
        if scope in ('all', 'tasks'):
            accessible_tasks = get_accessible_tasks(request.user)
            results['tasks'] = accessible_tasks.filter(
                Q(title__icontains=q) | Q(content__icontains=q) | Q(id__icontains=q)
            ).select_related('project', 'user').distinct()[:10]

        # Reports
        # 报告
        if scope in ('all', 'reports'):
            accessible_reports = get_accessible_reports(request.user)
            results['reports'] = accessible_reports.filter(
                Q(today_work__icontains=q) | 
                Q(progress_issues__icontains=q) |
                Q(tomorrow_plan__icontains=q)
            ).select_related('user').distinct()[:10]
            
        # Users
        # 用户
        if scope in ('all', 'users'):
            results['users'] = get_user_model().objects.filter(
                Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
            )[:10]

        log_action(request, 'search', f"global_search q={q} scope={scope}")

    context = {
        'q': q,
        'scope': scope,
        'results': results,
        'total_hits': len(results['projects']) + len(results['tasks']) + len(results['reports']) + len(results['users'])
    }
    return render(request, 'reports/global_search.html', context)
