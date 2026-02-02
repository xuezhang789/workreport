from django.db.models import Count, Avg, F, Q, DurationField, ExpressionWrapper
from django.utils import timezone
from django.contrib.auth import get_user_model
from ..models import Task, DailyReport, Profile, Project
from core.constants import TaskStatus
import statistics
from collections import defaultdict

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
    completed_tasks_iter = tasks.filter(status__in=[TaskStatus.DONE, TaskStatus.CLOSED], completed_at__isnull=False).select_related('project', 'user__profile')
    
    project_durations = defaultdict(list)
    role_durations = defaultdict(list)
    user_durations = defaultdict(list)
    
    for t in completed_tasks_iter:
        if t.completed_at and t.created_at:
            duration = (t.completed_at - t.created_at).total_seconds() / 3600
            if t.project and t.project.name:
                project_durations[t.project.name].append(duration)
            if hasattr(t.user, 'profile') and t.user.profile.position:
                role_durations[t.user.profile.position].append(duration)
            if t.user.username:
                user_durations[t.user.username].append(duration)

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
    overall_total = tasks.count()
    overall_overdue = tasks.filter(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now()).count()
    
    completed_qs = tasks.filter(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])
    completed_count = completed_qs.count()
    
    if completed_count > 0:
        # 准时：completed_at <= due_at 或 due_at 为 NULL
        # 注意：在某些数据库中，带有 NULL 的 F() 可能需要小心，但 Django 通常会处理它。
        # 如果 due_at 为 None，我们要么假设准时（要么与 SLA 无关）。
        on_time_count = completed_qs.filter(
            Q(due_at__isnull=True) | Q(completed_at__lte=F('due_at'))
        ).count()
        overall_sla_on_time_rate = (on_time_count / completed_count) * 100
    else:
        overall_sla_on_time_rate = 0

    # 计算总体交付周期
    completed_tasks_durations = []
    # 重用 completed_qs 但我们需要时间。
    # 我们可以只获取时间戳以最大限度地减少内存使用
    completed_times = completed_qs.filter(completed_at__isnull=False, created_at__isnull=False).values_list('created_at', 'completed_at')
    
    for start, end in completed_times:
        if start and end:
            completed_tasks_durations.append((end - start).total_seconds() / 3600)
            
    overall_lead_avg = statistics.mean(completed_tasks_durations) if completed_tasks_durations else None
    overall_lead_p50 = statistics.median(completed_tasks_durations) if completed_tasks_durations else None

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

def get_advanced_report_data(project_id=None):
    """
    获取高级报表图表的数据（甘特图、燃尽图、累积流图）。
    """
    User = get_user_model()
    
    tasks = Task.objects.all()
    if project_id:
        tasks = tasks.filter(project_id=project_id)
        
    # --- 1. 甘特图数据 ---
    # 为甘特图准备任务
    gantt_data = []
    gantt_tasks = tasks.select_related('user').order_by('created_at')[:100] # 限制以提高性能
    
    for t in gantt_tasks:
        start = t.created_at
        end = t.completed_at or t.due_at or (start + timezone.timedelta(days=2)) # 回退结束时间
        
        # 确保结束时间在开始时间之后
        if end < start:
            end = start + timezone.timedelta(hours=1)
            
        progress = 100 if t.status in (TaskStatus.DONE, TaskStatus.CLOSED) else (50 if t.status == TaskStatus.IN_PROGRESS else 0)
        
        gantt_data.append({
            'id': str(t.id),
            'name': t.title,
            'start': start.strftime('%Y-%m-%d'),
            'end': end.strftime('%Y-%m-%d'),
            'progress': progress,
            'dependencies': None, # 如果模型支持，添加依赖逻辑
            'custom_class': f'gantt-bar-{t.status}' 
        })

    # --- 2. 燃尽图数据 ---
    # 理想线 vs 实际剩余
    # 简单方法：计算总任务数，随时间减去已完成数
    
    burndown_data = {'labels': [], 'ideal': [], 'actual': []}
    
    if tasks.exists():
        earliest_task = tasks.order_by('created_at').first()
        earliest = earliest_task.created_at.date() if earliest_task else timezone.now().date()
        latest = timezone.now().date()
        
        # 创建日期范围
        date_range = []
        curr = earliest
        while curr <= latest:
            date_range.append(curr)
            curr += timezone.timedelta(days=1)
            
        # 限制点数以避免图表混乱（例如最多 30 个点）
        if len(date_range) > 30:
            step = len(date_range) // 30
            date_range = date_range[::step]
            
        total_tasks_count = tasks.count()
        
        # 计算理想值：从总数线性下降到 0
        days_span = (latest - earliest).days or 1
        
        for i, d in enumerate(date_range):
            burndown_data['labels'].append(d.strftime('%Y-%m-%d'))
            
            # Ideal
            ideal_val = max(0, total_tasks_count - (i * (total_tasks_count / len(date_range))))
            burndown_data['ideal'].append(round(ideal_val, 1))
            
            # 实际值：总数 - 截至日期 d 已完成数
            completed_count = tasks.filter(status__in=[TaskStatus.DONE, TaskStatus.CLOSED], completed_at__date__lte=d).count()
            actual_remaining = total_tasks_count - completed_count
            burndown_data['actual'].append(actual_remaining)

    # --- 3. 累积流图数据 ---
    # 累积流图
    
    cfd_data = {'labels': [], 'datasets': []}
    if tasks.exists() and burndown_data['labels']:
        cfd_data['labels'] = burndown_data['labels']
        
        # 大致重用日期范围逻辑或从标签重新解析
        # 仅重用逻辑：
        earliest_task = tasks.order_by('created_at').first()
        earliest = earliest_task.created_at.date() if earliest_task else timezone.now().date()
        latest = timezone.now().date()
        
        date_range = []
        curr = earliest
        while curr <= latest:
            date_range.append(curr)
            curr += timezone.timedelta(days=1)
            
        if len(date_range) > 30:
            step = len(date_range) // 30
            date_range = date_range[::step]
        
        pending_data = []
        completed_data = []
        
        for d in date_range:
            # 第 d 天结束时的快照
            # 已完成
            comp = tasks.filter(status__in=[TaskStatus.DONE, TaskStatus.CLOSED], completed_at__date__lte=d).count()
            completed_data.append(comp)
            
            # 待办：截至 d 创建 - 已完成
            created_by_d = tasks.filter(created_at__date__lte=d).count()
            todo = created_by_d - comp
            
            pending_data.append(todo)
            
        cfd_data['datasets'] = [
            {'name': '待处理 / To Do', 'data': pending_data},
            {'name': '已完成 / Done', 'data': completed_data},
        ]

    return {
        'gantt': gantt_data,
        'burndown': burndown_data,
        'cfd': cfd_data
    }
