from django.db.models import Count, Avg, F, Q, DurationField, ExpressionWrapper, Min
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.contrib.auth import get_user_model
from ..models import Task, DailyReport, Profile, Project
from core.constants import TaskStatus
import statistics
from collections import defaultdict
import bisect

def get_performance_stats(start_date=None, end_date=None, project_id=None, role_filter=None, q=None, accessible_projects=None):
    """
    计算绩效看板的绩效统计数据。
    """
    User = get_user_model()
    
    # 基础查询集
    tasks = Task.objects.select_related('project', 'user', 'user__profile')
    reports = DailyReport.objects.select_related('user', 'user__profile')
    
    if accessible_projects is not None:
        tasks = tasks.filter(project__in=accessible_projects)
        reports = reports.filter(projects__in=accessible_projects).distinct()

    # 应用过滤器
    if start_date:
        tasks = tasks.filter(created_at__date__gte=start_date)
        reports = reports.filter(date__gte=start_date)
    if end_date:
        tasks = tasks.filter(created_at__date__lte=end_date)
        reports = reports.filter(date__lte=end_date)
        
    if project_id:
        tasks = tasks.filter(project_id=project_id)
        # 简单模式下的报告没有直接的项目链接，如果需要，可以通过用户项目成员资格或类似逻辑进行过滤
        # 目前，除非我们要交叉引用用户，否则我们保留未过滤项目的报告
        
    if role_filter:
        tasks = tasks.filter(user__profile__position=role_filter)
        reports = reports.filter(user__profile__position=role_filter)

    if q:
        tasks = tasks.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q))
        reports = reports.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q))

    # --- 预计算交付周期（优化）---
    # Optimized: Fetch only necessary fields using values() to avoid model instantiation overhead
    completed_data = tasks.filter(
        status__in=[TaskStatus.DONE, TaskStatus.CLOSED], 
        completed_at__isnull=False
    ).values(
        'project__name', 
        'user__profile__position', 
        'user__username', 
        'created_at', 
        'completed_at'
    )
    
    project_durations = defaultdict(list)
    role_durations = defaultdict(list)
    user_durations = defaultdict(list)
    all_durations = []
    
    for item in completed_data:
        if item['completed_at'] and item['created_at']:
            duration = (item['completed_at'] - item['created_at']).total_seconds() / 3600
            all_durations.append(duration)
            
            if item['project__name']:
                project_durations[item['project__name']].append(duration)
            if item['user__profile__position']:
                role_durations[item['user__profile__position']].append(duration)
            if item['user__username']:
                user_durations[item['user__username']].append(duration)

    # --- 1. 项目统计 ---
    project_stats = []
    project_metrics = tasks.values('project__name').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        # lead_time=Avg(F('completed_at') - F('created_at'), filter=Q(status='completed')) # SQLite 对平均持续时间的限制
    ).order_by('-total')

    # 在 Python 中计算交付周期以安全支持所有数据库或使用复杂的数据库函数
    # 为了简单和兼容性，我们将在这里进行聚合或稍后改进
    # 让我们做一个单独的查询来计算交付周期，以避免复杂的分组问题
    
    for p in project_metrics:
        total = p['total']
        completed = p['completed']
        overdue = p['overdue']
        
        # 计算交付周期（用于显示的近似值）
        # 使用预计算的持续时间
        durations = project_durations.get(p['project__name'], [])
        
        lead_time_avg = statistics.mean(durations) if durations else None
        lead_time_p50 = statistics.median(durations) if durations else None

        project_stats.append({
            'project': p['project__name'],
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total else 0,
            'overdue_rate': (overdue / total * 100) if total else 0,
            'sla_on_time_rate': 0, # Placeholder
            'lead_time_avg': round(lead_time_avg, 1) if lead_time_avg is not None else None,
            'lead_time_p50': round(lead_time_p50, 1) if lead_time_p50 is not None else None,
        })

    # --- 2. 角色统计 ---
    role_stats = []
    role_metrics = tasks.values('user__profile__position').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now()))
    ).order_by('-total')
    
    role_map = dict(Profile.ROLE_CHOICES)
    
    for r in role_metrics:
        role_code = r['user__profile__position']
        if not role_code: continue
        
        total = r['total']
        completed = r['completed']
        overdue = r['overdue']
        
        # 每个角色的交付周期
        durations = role_durations.get(role_code, [])

        lead_time_avg = statistics.mean(durations) if durations else None
        lead_time_p50 = statistics.median(durations) if durations else None

        role_stats.append({
            'role_label': role_map.get(role_code, role_code),
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total else 0,
            'overdue_rate': (overdue / total * 100) if total else 0,
            'sla_on_time_rate': 0, # Placeholder
            'lead_time_avg': round(lead_time_avg, 1) if lead_time_avg is not None else None,
            'lead_time_p50': round(lead_time_p50, 1) if lead_time_p50 is not None else None,
        })

    # --- 3. 用户统计 ---
    user_stats = []
    user_metrics = tasks.values('user__username', 'user__first_name', 'user__last_name').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now()))
    ).order_by('-total')[:50] # 前 50 名用户

    for u in user_metrics:
        total = u['total']
        completed = u['completed']
        overdue = u['overdue']
        
        name_part = f"{u['user__first_name']} {u['user__last_name']}".strip() or u['user__username']
        full_label = f"{name_part} @{u['user__username']}"
        
        # 每个用户的交付周期（可能很昂贵，如果需要限制范围）
        durations = user_durations.get(u['user__username'], [])

        lead_time_avg = statistics.mean(durations) if durations else None
        lead_time_p50 = statistics.median(durations) if durations else None

        user_stats.append({
            'user_label': full_label,
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total else 0,
            'overdue_rate': (overdue / total * 100) if total else 0,
            'sla_on_time_rate': 0, # Placeholder
            'lead_time_avg': round(lead_time_avg, 1) if lead_time_avg is not None else None,
            'lead_time_p50': round(lead_time_p50, 1) if lead_time_p50 is not None else None,
        })
        
    # --- 4. 连签统计（占位符逻辑）---
    role_streaks = []
    # 连签的实现需要复杂的每日分析，暂时保持简单或为空

    # --- 5. 总体统计 ---
    # Optimized: Use single aggregate query for counts
    overall_aggs = tasks.aggregate(
        total=Count('id'),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        on_time=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]) & (Q(due_at__isnull=True) | Q(completed_at__lte=F('due_at'))))
    )
    
    overall_total = overall_aggs['total']
    overall_overdue = overall_aggs['overdue']
    completed_count = overall_aggs['completed']
    on_time_count = overall_aggs['on_time']
    
    if completed_count > 0:
        overall_sla_on_time_rate = (on_time_count / completed_count) * 100
    else:
        overall_sla_on_time_rate = 0

    # 计算总体交付周期
    # Optimized: Reuse all_durations calculated earlier
    overall_lead_avg = statistics.mean(all_durations) if all_durations else None
    overall_lead_p50 = statistics.median(all_durations) if all_durations else None

    return {
        'project_stats': project_stats,
        'role_stats': role_stats,
        'user_stats': user_stats,
        'role_streaks': role_streaks,
        'overall_total': overall_total,
        'overall_overdue': overall_overdue,
        'overall_sla_on_time_rate': round(overall_sla_on_time_rate, 1),
        'overall_lead_avg': round(overall_lead_avg, 1) if overall_lead_avg is not None else None,
        'overall_lead_p50': round(overall_lead_p50, 1) if overall_lead_p50 is not None else None,
    }

def generate_gantt_data(project_id=None, page=1, limit=50):
    tasks = Task.objects.all()
    if project_id:
        tasks = tasks.filter(project_id=project_id)
    
    total = tasks.count()
    start = (page - 1) * limit
    end = start + limit
    
    # Use select_related to avoid N+1
    page_tasks = tasks.select_related('user').order_by('created_at')[start:end]
    
    data = []
    for t in page_tasks:
        s = t.created_at
        e = t.completed_at or t.due_at or (s + timezone.timedelta(days=2))
        if e < s: e = s + timezone.timedelta(hours=1)
        
        progress = 100 if t.status in ('done', 'closed') else (50 if t.status == 'in_progress' else 0)
        
        data.append({
            'id': str(t.id),
            'name': t.title,
            'start': s.strftime('%Y-%m-%d'),
            'end': e.strftime('%Y-%m-%d'),
            'progress': progress,
            'custom_class': f'gantt-bar-{t.status}'
        })
    
    return {
        'total': total,
        'page': page,
        'limit': limit,
        'data': data
    }

def generate_burndown_data(project_id=None):
    tasks = Task.objects.all()
    if project_id:
        tasks = tasks.filter(project_id=project_id)
        
    if not tasks.exists():
        return {'labels': [], 'ideal': [], 'actual': []}
        
    earliest = tasks.aggregate(m=Min('created_at'))['m'].date()
    latest = timezone.now().date()
    total_tasks = tasks.count()
    
    # DB Aggregation: Daily completion counts
    completions = tasks.filter(
        status__in=['done', 'closed'], 
        completed_at__isnull=False
    ).annotate(
        date=TruncDate('completed_at')
    ).values('date').annotate(c=Count('id')).order_by('date')
    
    comp_map = {item['date']: item['c'] for item in completions}
    
    # Sampling
    date_range = []
    curr = earliest
    while curr <= latest:
        date_range.append(curr)
        curr += timezone.timedelta(days=1)
    
    if len(date_range) > 30:
        step = len(date_range) // 30
        date_range = date_range[::step]
        
    labels = []
    ideal = []
    actual = []
    
    sorted_comp_dates = sorted(comp_map.keys())
    
    for i, d in enumerate(date_range):
        labels.append(d.strftime('%Y-%m-%d'))
        
        # Ideal
        ideal_val = max(0, total_tasks - (i * (total_tasks / len(date_range))))
        ideal.append(round(ideal_val, 1))
        
        # Actual
        done_so_far = sum(comp_map[cd] for cd in sorted_comp_dates if cd <= d)
        actual.append(total_tasks - done_so_far)
        
    return {'labels': labels, 'ideal': ideal, 'actual': actual}

def generate_cfd_data(project_id=None):
    tasks = Task.objects.all()
    if project_id:
        tasks = tasks.filter(project_id=project_id)
    
    if not tasks.exists():
         return {'labels': [], 'datasets': []}

    earliest = tasks.aggregate(m=Min('created_at'))['m'].date()
    latest = timezone.now().date()
    
    # Aggregations
    creations = tasks.annotate(date=TruncDate('created_at')).values('date').annotate(c=Count('id')).order_by('date')
    create_map = {item['date']: item['c'] for item in creations}
    
    completions = tasks.filter(status__in=['done', 'closed'], completed_at__isnull=False)\
        .annotate(date=TruncDate('completed_at')).values('date').annotate(c=Count('id')).order_by('date')
    comp_map = {item['date']: item['c'] for item in completions}
    
    date_range = []
    curr = earliest
    while curr <= latest:
        date_range.append(curr)
        curr += timezone.timedelta(days=1)
        
    if len(date_range) > 30:
        step = len(date_range) // 30
        date_range = date_range[::step]
        
    labels = []
    pending_data = []
    completed_data = []
    
    sorted_create_dates = sorted(create_map.keys())
    sorted_comp_dates = sorted(comp_map.keys())
    
    for d in date_range:
        labels.append(d.strftime('%Y-%m-%d'))
        
        created_so_far = sum(create_map[cd] for cd in sorted_create_dates if cd <= d)
        done_so_far = sum(comp_map[cd] for cd in sorted_comp_dates if cd <= d)
        
        completed_data.append(done_so_far)
        pending_data.append(created_so_far - done_so_far)
        
    return {
        'labels': labels,
        'datasets': [
            {'name': '待处理 / To Do', 'data': pending_data},
            {'name': '已完成 / Done', 'data': completed_data}
        ]
    }

def get_advanced_report_data(project_id=None):
    """
    Deprecated: Use individual generate_* functions.
    Wrapper for backward compatibility.
    """
    return {
        'gantt': generate_gantt_data(project_id, limit=100)['data'],
        'burndown': generate_burndown_data(project_id),
        'cfd': generate_cfd_data(project_id)
    }

