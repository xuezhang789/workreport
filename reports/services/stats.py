from django.db.models import Count, Avg, F, Q, DurationField, ExpressionWrapper
from django.utils import timezone
from django.contrib.auth import get_user_model
from ..models import Task, DailyReport, Profile, Project
import statistics
from collections import defaultdict

def get_performance_stats(start_date=None, end_date=None, project_id=None, role_filter=None, q=None, accessible_projects=None):
    """
    Calculate performance statistics for the performance board.
    """
    User = get_user_model()
    
    # Base QuerySets
    tasks = Task.objects.select_related('project', 'user', 'user__profile')
    reports = DailyReport.objects.select_related('user', 'user__profile')
    
    if accessible_projects is not None:
        tasks = tasks.filter(project__in=accessible_projects)
        reports = reports.filter(projects__in=accessible_projects).distinct()

    # Apply filters
    if start_date:
        tasks = tasks.filter(created_at__date__gte=start_date)
        reports = reports.filter(date__gte=start_date)
    if end_date:
        tasks = tasks.filter(created_at__date__lte=end_date)
        reports = reports.filter(date__lte=end_date)
        
    if project_id:
        tasks = tasks.filter(project_id=project_id)
        # Reports don't have direct project link in simple mode, filtering by user project membership or similar logic if needed
        # For now, we'll keep reports unfiltered by project unless we cross-reference users
        
    if role_filter:
        tasks = tasks.filter(user__profile__position=role_filter)
        reports = reports.filter(user__profile__position=role_filter)

    if q:
        tasks = tasks.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q))
        reports = reports.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q))

    # --- Pre-calculate Lead Times (Optimization) ---
    completed_tasks_iter = tasks.filter(status__in=['done', 'closed'], completed_at__isnull=False).select_related('project', 'user__profile')
    
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

    # --- 1. Project Stats ---
    project_stats = []
    project_metrics = tasks.values('project__name').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=['done', 'closed'])),
        overdue=Count('id', filter=Q(status__in=['todo', 'in_progress', 'blocked', 'in_review'], due_at__lt=timezone.now())),
        # lead_time=Avg(F('completed_at') - F('created_at'), filter=Q(status='completed')) # SQLite limitation for Avg Duration
    ).order_by('-total')

    # Calculate lead times in python to support all DBs safely or use complex DB functions
    # For simplicity and compatibility, we'll do aggregation here or improve later
    # Let's do a separate query for lead times to avoid complex grouping issues
    
    for p in project_metrics:
        total = p['total']
        completed = p['completed']
        overdue = p['overdue']
        
        # Calculate Lead Time (approximate for display)
        # Use pre-calculated durations
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

    # --- 2. Role Stats ---
    role_stats = []
    role_metrics = tasks.values('user__profile__position').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=['done', 'closed'])),
        overdue=Count('id', filter=Q(status__in=['todo', 'in_progress', 'blocked', 'in_review'], due_at__lt=timezone.now()))
    ).order_by('-total')
    
    role_map = dict(Profile.ROLE_CHOICES)
    
    for r in role_metrics:
        role_code = r['user__profile__position']
        if not role_code: continue
        
        total = r['total']
        completed = r['completed']
        overdue = r['overdue']
        
        # Lead time per role
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

    # --- 3. User Stats ---
    user_stats = []
    user_metrics = tasks.values('user__username', 'user__first_name', 'user__last_name').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=['done', 'closed'])),
        overdue=Count('id', filter=Q(status__in=['todo', 'in_progress', 'blocked', 'in_review'], due_at__lt=timezone.now()))
    ).order_by('-total')[:50] # Top 50 users

    for u in user_metrics:
        total = u['total']
        completed = u['completed']
        overdue = u['overdue']
        
        full_name = f"{u['user__first_name']} {u['user__last_name']}".strip() or u['user__username']
        
        # Lead time per user (can be expensive, limit scope if needed)
        durations = user_durations.get(u['user__username'], [])

        lead_time_avg = statistics.mean(durations) if durations else None
        lead_time_p50 = statistics.median(durations) if durations else None

        user_stats.append({
            'user_label': full_name,
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total else 0,
            'overdue_rate': (overdue / total * 100) if total else 0,
            'sla_on_time_rate': 0, # Placeholder
            'lead_time_avg': round(lead_time_avg, 1) if lead_time_avg is not None else None,
            'lead_time_p50': round(lead_time_p50, 1) if lead_time_p50 is not None else None,
        })
        
    # --- 4. Streak Stats (Placeholder logic) ---
    role_streaks = []
    # Implementation of streaks requires complex daily analysis, keeping it simple or empty for now

    # --- 5. Overall Stats ---
    overall_total = tasks.count()
    overall_overdue = tasks.filter(status__in=['todo', 'in_progress', 'blocked', 'in_review'], due_at__lt=timezone.now()).count()
    
    completed_qs = tasks.filter(status__in=['done', 'closed'])
    completed_count = completed_qs.count()
    
    if completed_count > 0:
        # On time: completed_at <= due_at OR due_at is NULL
        # Note: In some DBs F() with NULL might need care, but Django handles it usually.
        # If due_at is None, we assume on time (or irrelevant to SLA).
        on_time_count = completed_qs.filter(
            Q(due_at__isnull=True) | Q(completed_at__lte=F('due_at'))
        ).count()
        overall_sla_on_time_rate = (on_time_count / completed_count) * 100
    else:
        overall_sla_on_time_rate = 0

    # Calculate Overall Lead Time
    completed_tasks_durations = []
    # Reuse completed_qs but we need the times.
    # We can fetch just the timestamps to minimize memory usage
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
    Get data for advanced reporting charts (Gantt, Burndown, CFD).
    """
    User = get_user_model()
    
    tasks = Task.objects.all()
    if project_id:
        tasks = tasks.filter(project_id=project_id)
        
    # --- 1. Gantt Data ---
    # Prepare tasks for Gantt chart
    gantt_data = []
    gantt_tasks = tasks.select_related('user').order_by('created_at')[:100] # Limit for performance
    
    for t in gantt_tasks:
        start = t.created_at
        end = t.completed_at or t.due_at or (start + timezone.timedelta(days=2)) # Fallback end
        
        # Ensure end is after start
        if end < start:
            end = start + timezone.timedelta(hours=1)
            
        progress = 100 if t.status in ('done', 'closed') else (50 if t.status == 'in_progress' else 0)
        
        gantt_data.append({
            'id': str(t.id),
            'name': t.title,
            'start': start.strftime('%Y-%m-%d'),
            'end': end.strftime('%Y-%m-%d'),
            'progress': progress,
            'dependencies': None, # Add dependency logic if model supports it
            'custom_class': f'gantt-bar-{t.status}' 
        })

    # --- 2. Burndown Data ---
    # Ideal line vs Actual remaining
    # Simple approach: Count total tasks, subtract completed over time
    
    burndown_data = {'labels': [], 'ideal': [], 'actual': []}
    
    if tasks.exists():
        earliest_task = tasks.order_by('created_at').first()
        earliest = earliest_task.created_at.date() if earliest_task else timezone.now().date()
        latest = timezone.now().date()
        
        # Create date range
        date_range = []
        curr = earliest
        while curr <= latest:
            date_range.append(curr)
            curr += timezone.timedelta(days=1)
            
        # Limit points to avoid chart clutter (e.g. max 30 points)
        if len(date_range) > 30:
            step = len(date_range) // 30
            date_range = date_range[::step]
            
        total_tasks_count = tasks.count()
        
        # Calculate Ideal: linear drop from Total to 0
        days_span = (latest - earliest).days or 1
        
        for i, d in enumerate(date_range):
            burndown_data['labels'].append(d.strftime('%Y-%m-%d'))
            
            # Ideal
            ideal_val = max(0, total_tasks_count - (i * (total_tasks_count / len(date_range))))
            burndown_data['ideal'].append(round(ideal_val, 1))
            
            # Actual: Total - Completed by date d
            completed_count = tasks.filter(status__in=['done', 'closed'], completed_at__date__lte=d).count()
            actual_remaining = total_tasks_count - completed_count
            burndown_data['actual'].append(actual_remaining)

    # --- 3. CFD Data ---
    # Cumulative Flow Diagram
    
    cfd_data = {'labels': [], 'datasets': []}
    if tasks.exists() and burndown_data['labels']:
        cfd_data['labels'] = burndown_data['labels']
        
        # Reuse date_range logic roughly or re-parse from labels
        # Just reuse the logic:
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
            # Snapshot at end of day d
            # Completed
            comp = tasks.filter(status__in=['done', 'closed'], completed_at__date__lte=d).count()
            completed_data.append(comp)
            
            # Todo: Created by d - Completed
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
