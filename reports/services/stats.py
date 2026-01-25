from django.db.models import Count, Q, F, Avg, Case, When, Value, IntegerField, Min
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.core.cache import cache
from reports.models import Task, DailyReport, Project, Profile
from django.contrib.auth import get_user_model
import statistics
from datetime import timedelta

def get_performance_stats(start_date=None, end_date=None, project_id=None, role_filter=None, q=None):
    """
    Optimized performance stats calculation using DB aggregation.
    """
    cache_key = f"performance_stats_v2_{start_date}_{end_date}_{project_id}_{role_filter}_{q}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    generated_at = timezone.now()
    
    # Base QuerySet
    tasks_qs = Task.objects.all()
    if start_date:
        tasks_qs = tasks_qs.filter(created_at__date__gte=start_date)
    if end_date:
        tasks_qs = tasks_qs.filter(created_at__date__lte=end_date)
    if project_id and isinstance(project_id, int):
        tasks_qs = tasks_qs.filter(project_id=project_id)
    if role_filter and role_filter in dict(Profile.ROLE_CHOICES):
        tasks_qs = tasks_qs.filter(user__profile__position=role_filter)
    if q:
        tasks_qs = tasks_qs.filter(
            Q(user__username__icontains=q) | 
            Q(user__first_name__icontains=q) | 
            Q(user__last_name__icontains=q)
        )

    # Aggregation Helpers
    def get_stats_aggregate(queryset, group_by_field):
        return queryset.values(group_by_field).annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='completed')),
            overdue=Count('id', filter=Q(status='overdue')),
            on_time=Count('id', filter=Q(status='completed', completed_at__lte=F('due_at'))), # Simplified on_time check
        ).order_by('-total')

    # Project Stats
    project_stats_raw = get_stats_aggregate(tasks_qs, 'project__name')
    project_stats = []
    for item in project_stats_raw:
        total = item['total']
        if not total: continue
        project_stats.append({
            'project': item['project__name'] or '未分配 / Unassigned',
            'total': total,
            'completed': item['completed'],
            'overdue': item['overdue'],
            'completion_rate': (item['completed'] / total * 100),
            'overdue_rate': (item['overdue'] / total * 100),
            'sla_on_time_rate': (item['on_time'] / item['completed'] * 100) if item['completed'] else 0,
            'lead_time_p50': 0, # Placeholder
        })

    # Role Stats
    role_stats_raw = tasks_qs.values('user__profile__position').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        overdue=Count('id', filter=Q(status='overdue')),
    )
    role_map = dict(Profile.ROLE_CHOICES)
    role_stats = []
    for item in role_stats_raw:
        role_code = item['user__profile__position']
        total = item['total']
        if not total: continue
        role_stats.append({
            'role': role_code,
            'role_label': role_map.get(role_code, role_code or '未知 / Unknown'),
            'total': total,
            'completed': item['completed'],
            'overdue': item['overdue'],
            'completion_rate': (item['completed'] / total * 100),
            'overdue_rate': (item['overdue'] / total * 100),
        })

    # User Stats
    User = get_user_model()
    user_stats_raw = get_stats_aggregate(tasks_qs, 'user__id')
    user_ids = [item['user__id'] for item in user_stats_raw if item['user__id']]
    user_map = {u.id: (u.get_full_name() or u.username) for u in User.objects.filter(id__in=user_ids)}
    
    user_stats = []
    for item in user_stats_raw:
        uid = item['user__id']
        if not uid: continue
        total = item['total']
        user_stats.append({
            'user_id': uid,
            'user_label': user_map.get(uid, '未知 / Unknown'),
            'total': total,
            'completed': item['completed'],
            'overdue': item['overdue'],
            'completion_rate': (item['completed'] / total * 100) if total else 0,
            'overdue_rate': (item['overdue'] / total * 100) if total else 0,
        })

    # Trend (Optimized)
    trend = []
    end_for_trend = end_date or timezone.localdate()
    default_span = timedelta(days=6)
    max_span = timedelta(days=30)
    if start_date:
        span_start = max(start_date, end_for_trend - max_span)
    else:
        span_start = end_for_trend - default_span
    
    trend_qs = DailyReport.objects.filter(
        date__gte=span_start, 
        date__lte=end_for_trend, 
        status='submitted'
    ).values('date').annotate(count=Count('id')).order_by('date')
    
    trend_dict = {item['date']: item['count'] for item in trend_qs}
    curr = span_start
    while curr <= end_for_trend:
        trend.append({'date': curr, 'count': trend_dict.get(curr, 0)})
        curr += timedelta(days=1)

    # Streak Calculation - 优化连签计算，避免N+1查询
    submissions = DailyReport.objects.filter(status='submitted').values('user_id', 'date')
    user_dates = {}
    for item in submissions:
        user_dates.setdefault(item['user_id'], set()).add(item['date'])
    
    today = timezone.localdate()
    streaks_map = {}
    for uid, dates in user_dates.items():
        curr = today
        streak = 0
        while curr in dates:
            streak += 1
            curr = curr - timedelta(days=1)
        streaks_map[uid] = streak

    role_streaks = []
    
    # Optimization: Fetch all users' roles in one query
    user_roles = list(User.objects.filter(profile__position__isnull=False).values('id', 'profile__position'))
    
    # Group user IDs by role
    role_users_map = {}
    for item in user_roles:
        r = item['profile__position']
        role_users_map.setdefault(r, []).append(item['id'])

    for role_key, role_label in Profile.ROLE_CHOICES:
        uids = role_users_map.get(role_key, [])
        values = [streaks_map.get(uid, 0) for uid in uids] or [0]
        avg_streak = sum(values) / len(values) if values else 0
        role_streaks.append({
            'role': role_key,
            'role_label': role_label,
            'avg_streak': round(avg_streak, 1),
            'max_streak': max(values) if values else 0,
        })

    # Overall Stats
    overall_agg = tasks_qs.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        overdue=Count('id', filter=Q(status='overdue')),
        on_time=Count('id', filter=Q(status='completed', completed_at__lte=F('due_at'))),
    )
    
    # Calculate simple lead time avg (ignoring extreme outliers if we wanted, but keeping simple for now)
    # Note: DB-level duration avg is tricky across backends. 
    # If tasks_qs is not huge, we could calculate lead time for completed tasks here.
    # But for "Optimized", we skip it or accept it might be heavy if we load all completed tasks.
    # We'll skip lead time calculation for now to ensure performance.
    
    result = {
        'project_stats': project_stats,
        'role_stats': role_stats,
        'trend': trend,
        'generated_at': generated_at,
        'user_stats': user_stats,
        'role_streaks': role_streaks,
        'overall_total': overall_agg['total'],
        'overall_completed': overall_agg['completed'],
        'overall_overdue': overall_agg['overdue'],
        'overall_sla_on_time_rate': (overall_agg['on_time'] / overall_agg['completed'] * 100) if overall_agg['completed'] else 0,
        'overall_lead_avg': 0, # Placeholder
        'overall_lead_p50': 0, # Placeholder
    }
    
    cache.set(cache_key, result, 600)
    return result


def get_advanced_report_data(project_id=None):
    """
    Generate data for Gantt, Burndown, and Cumulative Flow diagrams.
    """
    tasks_qs = Task.objects.select_related('user', 'project').all()
    if project_id:
        tasks_qs = tasks_qs.filter(project_id=project_id)
    
    # 1. Gantt Data
    gantt_tasks = []
    for t in tasks_qs:
        start = t.created_at
        end = t.due_at or t.completed_at or (t.created_at + timedelta(days=1))
        if end < start:
            end = start + timedelta(hours=1)
            
        gantt_tasks.append({
            'title': t.title,
            'assignee': t.user.get_full_name() or t.user.username if t.user else 'Unassigned',
            'project': t.project.name if t.project else 'No Project',
            'status': t.status,
            'start_date': start.isoformat(),
            'due_date': end.isoformat(),
        })

    # 2. Timeline setup for Burndown & CFD
    if not tasks_qs.exists():
        return {'gantt': {'tasks': []}, 'burndown': {'data': []}, 'cfd': {'data': [], 'categories': []}}

    earliest = tasks_qs.aggregate(min_date=Min('created_at'))['min_date']
    if earliest:
        earliest = earliest.date()
    else:
        earliest = timezone.localdate()
    
    latest = timezone.localdate() # Up to today
    
    # Prepare timeline
    timeline_dates = []
    curr = earliest
    while curr <= latest:
        timeline_dates.append(curr)
        curr += timedelta(days=1)
        
    # Pre-fetch needed fields to memory to avoid N+1 in loop (assuming reasonable dataset size)
    # For very large datasets, this should be done with DB aggregation or window functions.
    task_events = []
    for t in tasks_qs:
        created = t.created_at.date()
        completed = t.completed_at.date() if t.status == 'completed' and t.completed_at else None
        task_events.append({'created': created, 'completed': completed})

    # 3. Burndown & CFD Calculation
    burndown_data = []
    cfd_data = {
        'dates': [d.isoformat() for d in timeline_dates],
        'total': [],
        'completed': [],
        'in_progress': [] # Derived: Total - Completed
    }
    
    for d in timeline_dates:
        # Count tasks existing on this date
        total_scope = sum(1 for t in task_events if t['created'] <= d)
        completed_count = sum(1 for t in task_events if t['completed'] and t['completed'] <= d)
        remaining = total_scope - completed_count
        
        burndown_data.append({
            'date': d.isoformat(),
            'remaining_tasks': remaining
        })
        
        cfd_data['total'].append(total_scope)
        cfd_data['completed'].append(completed_count)
        cfd_data['in_progress'].append(remaining)

    return {
        'gantt': {'tasks': gantt_tasks},
        'burndown': {'data': burndown_data, 'project_name': ''}, # Project name handled in view
        'cfd': cfd_data
    }
