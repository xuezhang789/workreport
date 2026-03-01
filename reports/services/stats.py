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
    
    # 基础查询集 (移除无用的 select_related，因为聚合查询会忽略它)
    tasks = Task.objects.all()
    # reports = DailyReport.objects.select_related('user', 'user__profile') # 移除未使用的 reports 查询
    
    if accessible_projects is not None:
        tasks = tasks.filter(project__in=accessible_projects)

    # 应用过滤器
    if start_date:
        tasks = tasks.filter(created_at__date__gte=start_date)
    if end_date:
        tasks = tasks.filter(created_at__date__lte=end_date)
        
    if project_id:
        tasks = tasks.filter(project_id=project_id)
        # 简单模式下的报告没有直接的项目链接，如果需要，可以通过用户项目成员资格或类似逻辑进行过滤
        # 目前，除非我们要交叉引用用户，否则我们保留未过滤项目的报告
        
    if role_filter:
        tasks = tasks.filter(user__profile__position=role_filter)

    if q:
        tasks = tasks.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q))

    # --- 1. 项目统计 ---
    project_stats = []
    project_metrics = tasks.values('project__name').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        sla_met=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]) & (Q(due_at__isnull=True) | Q(completed_at__lte=F('due_at')))),
        avg_lead_time=Avg(ExpressionWrapper(F('completed_at') - F('created_at'), output_field=DurationField()), filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]))
    ).order_by('-total')

    for p in project_metrics:
        total = p['total']
        completed = p['completed']
        overdue = p['overdue']
        sla_met = p['sla_met']
        
        # 使用数据库计算的平均交付周期
        db_lead_time_avg = p['avg_lead_time'].total_seconds() / 3600 if p['avg_lead_time'] else None
        
        project_stats.append({
            'project': p['project__name'],
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total else 0,
            'overdue_rate': (overdue / total * 100) if total else 0,
            'sla_on_time_rate': (sla_met / completed * 100) if completed else 0,
            'lead_time_avg': round(db_lead_time_avg, 1) if db_lead_time_avg is not None else None,
            'lead_time_p50': None, # P50 计算开销过大，已移除以提升性能
        })

    # --- 2. 角色统计 ---
    role_stats = []
    role_metrics = tasks.values('user__profile__position').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        avg_lead_time=Avg(ExpressionWrapper(F('completed_at') - F('created_at'), output_field=DurationField()), filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]))
    ).order_by('-total')
    
    role_map = dict(Profile.ROLE_CHOICES)
    
    for r in role_metrics:
        role_code = r['user__profile__position']
        if not role_code: continue
        
        total = r['total']
        completed = r['completed']
        overdue = r['overdue']
        
        db_lead_time_avg = r['avg_lead_time'].total_seconds() / 3600 if r['avg_lead_time'] else None

        role_stats.append({
            'role_label': role_map.get(role_code, role_code),
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total else 0,
            'overdue_rate': (overdue / total * 100) if total else 0,
            'sla_on_time_rate': 0, 
            'lead_time_avg': round(db_lead_time_avg, 1) if db_lead_time_avg is not None else None,
            'lead_time_p50': None,
        })

    # --- 3. 用户统计 ---
    user_stats = []
    user_metrics = tasks.values('user__username', 'user__first_name', 'user__last_name').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        avg_lead_time=Avg(ExpressionWrapper(F('completed_at') - F('created_at'), output_field=DurationField()), filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]))
    ).order_by('-total')[:50] # 前 50 名用户

    for u in user_metrics:
        total = u['total']
        completed = u['completed']
        overdue = u['overdue']
        
        name_part = f"{u['user__first_name']} {u['user__last_name']}".strip() or u['user__username']
        full_label = f"{name_part} @{u['user__username']}"
        
        db_lead_time_avg = u['avg_lead_time'].total_seconds() / 3600 if u['avg_lead_time'] else None

        user_stats.append({
            'user_label': full_label,
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total else 0,
            'overdue_rate': (overdue / total * 100) if total else 0,
            'sla_on_time_rate': 0, 
            'lead_time_avg': round(db_lead_time_avg, 1) if db_lead_time_avg is not None else None,
            'lead_time_p50': None,
        })
        
    # --- 4. 连签统计（占位符逻辑）---
    role_streaks = []

    # --- 5. 总体统计 ---
    overall_aggs = tasks.aggregate(
        total=Count('id'),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        on_time=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]) & (Q(due_at__isnull=True) | Q(completed_at__lte=F('due_at')))),
        avg_lead_time=Avg(ExpressionWrapper(F('completed_at') - F('created_at'), output_field=DurationField()), filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]))
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
    overall_lead_avg = overall_aggs['avg_lead_time'].total_seconds() / 3600 if overall_aggs['avg_lead_time'] else None
    
    return {
        'project_stats': project_stats,
        'role_stats': role_stats,
        'user_stats': user_stats,
        'role_streaks': role_streaks,
        'overall_total': overall_total,
        'overall_overdue': overall_overdue,
        'overall_sla_on_time_rate': round(overall_sla_on_time_rate, 1),
        'overall_lead_avg': round(overall_lead_avg, 1) if overall_lead_avg is not None else None,
        'overall_lead_p50': None,
    }

