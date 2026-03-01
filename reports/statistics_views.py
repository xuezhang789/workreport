from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.core.mail import send_mail
from django.db.models import Count, Q, F
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib import messages
from django.conf import settings

from tasks.models import Task
from work_logs.models import DailyReport
from projects.models import Project
from core.models import Profile, SystemSetting
from reports.services.stats import get_performance_stats as _performance_stats
from reports.services.guidance import generate_workbench_guidance
from reports.utils import get_accessible_projects
from core.utils import _admin_forbidden
from core.permissions import has_manage_permission
from tasks.services.sla import calculate_sla_info, get_sla_thresholds, get_sla_hours
from audit.utils import log_action
from datetime import timedelta
from core.constants import TaskStatus
import json

DEFAULT_SLA_REMIND = getattr(settings, 'SLA_REMIND_HOURS', 24)

import logging

logger = logging.getLogger(__name__)

def _send_weekly_digest(recipient, stats):
    """
    发送周报邮件给指定收件人。
    """
    try:
        subject = f"周报 / Weekly Digest: {timezone.localdate().isoformat()}"
        
        # 简单构建邮件内容 (目前为纯文本，可升级为 HTML)
        # 指标摘要
        total = stats.get('overall_total', 0)
        completed = stats.get('overall_completed', 0)
        overdue = stats.get('overall_overdue', 0)
        rate = stats.get('overall_rate', 0)
        
        message = f"""
        你好 / Hello,
        
        这是您的本周工作简报 / Here is your weekly work digest:
        
        --- 总体概况 / Overview ---
        任务总数 / Total Tasks: {total}
        已完成 / Completed: {completed}
        逾期任务 / Overdue: {overdue}
        完成率 / Completion Rate: {rate:.1f}%
        
        --- 项目详情 / Projects ---
        """
        
        for p in stats.get('project_stats', []):
            message += f"\nProject: {p['name']}\n"
            message += f"  Total: {p['total']}, Done: {p['completed']}, Overdue: {p['overdue']}\n"
            
        message += "\n\n请登录系统查看详情 / Please login to view details."
        
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
            fail_silently=False,
        )
        return True
    except Exception as e:
        # Log error in production
        logger.exception(f"Failed to send weekly digest: {e}") # 使用 logger.exception 记录堆栈信息
        return False

@login_required
def workbench(request):
    # 获取用户任务统计 (优化：使用聚合查询代替多次 count)
    
    tasks = Task.objects.filter(user=request.user)
    
    stats = tasks.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        in_progress=Count('id', filter=Q(status=TaskStatus.IN_PROGRESS)),
        pending=Count('id', filter=Q(status=TaskStatus.TODO))
    )
    
    total = stats['total']
    completed = stats['completed']
    overdue = stats['overdue']
    in_progress = stats['in_progress']
    pending = stats['pending']
    
    completion_rate = (completed / total * 100) if total else 0
    overdue_rate = (overdue / total * 100) if total else 0

    # 获取今日任务和即将到期任务数量
    today = timezone.now()
    today_tasks_count = tasks.filter(due_at__date=today.date()).exclude(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]).count()
    upcoming_tasks_count = tasks.filter(
        due_at__date__gt=today.date(),
        due_at__date__lte=today.date() + timedelta(days=3)
    ).exclude(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]).count()

    # 日报连签和今日日报状态
    today_date = timezone.localdate()
    # 优化：将连胜检查限制在最近的历史记录（365天）并使用 distinct
    qs_reports = DailyReport.objects.filter(
        user=request.user, 
        status='submitted'
    ).values_list('date', flat=True).distinct().order_by('-date')[:365]
    
    date_set = set(qs_reports)
    streak = 0
    curr = today_date
    
    # 检查今天是否提交以开始连胜计数，否则检查昨天
    if curr in date_set:
        streak += 1
        curr = curr - timedelta(days=1)
        while curr in date_set:
            streak += 1
            curr = curr - timedelta(days=1)
    elif (curr - timedelta(days=1)) in date_set:
        curr = curr - timedelta(days=1)
        while curr in date_set:
            streak += 1
            curr = curr - timedelta(days=1)
    
    # 检查今日是否已提交日报
    # 优化：如果 today_date 在 date_set 中（因为我们过滤了 status='submitted'），则 has_today_report 为 True
    
    has_today_report = today_date in date_set

    # 增强数据的项目燃尽图
    # 优化：直接查询任务以避免繁重的项目分组
    
    task_stats = Task.objects.filter(
        user=request.user,
        project__is_active=True
    ).values(
        'project__name', 'project__code'
    ).annotate(
        total_p=Count('id'),
        completed_p=Count('id', filter=Q(status__in=[TaskStatus.DONE, TaskStatus.CLOSED])),
        overdue_p=Count('id', filter=Q(status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED, TaskStatus.IN_REVIEW], due_at__lt=timezone.now())),
        in_progress_p=Count('id', filter=Q(status=TaskStatus.IN_PROGRESS))
    ).order_by('project__name')
    
    project_burndown = []
    for stat in task_stats:
        total_p = stat['total_p']
        completed_p = stat['completed_p']
        overdue_p = stat['overdue_p']
        in_progress_p = stat['in_progress_p']
        completion_rate_p = (completed_p / total_p * 100) if total_p else 0
        
        project_burndown.append({
            'project': stat['project__name'],
            'code': stat['project__code'],
            'total': total_p,
            'completed': completed_p,
            'in_progress': in_progress_p,
            'remaining': total_p - completed_p,
            'overdue': overdue_p,
            'completion_rate': completion_rate_p,
        })

    # recent reports with status
    # 具有状态的最近日报
    recent_reports = DailyReport.objects.filter(user=request.user).order_by('-date')[:5]

    # 获取用户角色用于个性化引导
    try:
        user_role = request.user.profile.position
    except (Profile.DoesNotExist, AttributeError):
        user_role = 'dev'
    
    # 智能引导文案生成
    guidance = generate_workbench_guidance(
        total, completed, overdue, in_progress, pending,
        streak, has_today_report, user_role, today_tasks_count, upcoming_tasks_count
    )

    return render(request, 'reports/workbench.html', {
        'task_stats': {
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'in_progress': in_progress,
            'pending': pending,
            'completion_rate': completion_rate,
            'overdue_rate': overdue_rate,
        },
        'today_tasks_count': today_tasks_count,
        'upcoming_tasks_count': upcoming_tasks_count,
        'project_burndown': project_burndown,
        'streak': streak,
        'has_today_report': has_today_report,
        'missing_today': not has_today_report,
        'recent_reports': recent_reports,
        'guidance': guidance,
        'user_role': user_role,
        'today': today_date,
    })


@login_required
def stats(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    qs = DailyReport.objects.all()
    sla_only = request.GET.get('sla_only') == '1'
    target_date = parse_date(request.GET.get('date') or '') or timezone.localdate()
    project_filter = request.GET.get('project')
    role_filter = (request.GET.get('role') or '').strip()
    cache_key_metrics = f"stats_metrics_v1_{target_date}_{project_filter}_{role_filter}"
    thresholds = get_sla_thresholds()
    generated_at = timezone.now()

    todays_user_ids = set(qs.filter(date=target_date).values_list('user_id', flat=True))
    # 优化：从 prefetch 中移除 'reports'，因为它会加载所有历史报告，这很重且未使用
    active_projects = Project.objects.filter(is_active=True).prefetch_related('members', 'managers')
    if project_filter and project_filter.isdigit():
        active_projects = active_projects.filter(id=int(project_filter))
    cache_key = f"stats_missing_{target_date}_{project_filter}_{role_filter}"
    cached = cache.get(cache_key)
    if cached:
        missing_projects, total_missing = cached
    else:
        missing_projects = []
        total_missing = 0
        
        # 预取所有需要的数据以避免 N+1 查询
        # 1. 收集所有活动项目中所有缺失的用户 ID
        all_missing_ids = set()
        project_missing_map = {} # pid -> [uid, uid...]
        
        # 确保我们使用预取的关联以避免 DB 命中
        # active_projects 已经预取了 'members', 'managers'
        
        for p in active_projects:
            # 使用 .all() 命中预取缓存，而不是 .values_list() 命中 DB
            member_ids = {u.id for u in p.members.all()}
            manager_ids = {u.id for u in p.managers.all()}
            expected_ids = member_ids | manager_ids
            if p.owner_id:
                expected_ids.add(p.owner_id)
                
            missing_ids = [uid for uid in expected_ids if uid not in todays_user_ids]
            if missing_ids:
                all_missing_ids.update(missing_ids)
                project_missing_map[p.id] = missing_ids

        # 2. 在一个查询中获取所有缺失的用户
        if all_missing_ids:
            users_qs = get_user_model().objects.select_related('profile').filter(id__in=all_missing_ids)
            users_map = {u.id: u for u in users_qs}
            
            # 3. 在一个查询中获取所有缺失用户的最后日报日期
            last_report_dates = DailyReport.objects.filter(
                user_id__in=all_missing_ids, 
                status='submitted'
            ).values('user_id').annotate(last_date=models.Max('date'))
            
            last_map = {item['user_id']: item['last_date'] for item in last_report_dates}
        else:
            users_map = {}
            last_map = {}

        # 4. 构建结果结构
        for p in active_projects:
            p_missing_ids = project_missing_map.get(p.id, [])
            if not p_missing_ids:
                continue
                
            filtered_users = []
            for uid in p_missing_ids:
                u = users_map.get(uid)
                if not u: continue
                
                # 在内存中应用角色过滤器
                if role_filter in dict(Profile.ROLE_CHOICES):
                    if not hasattr(u, 'profile') or u.profile.position != role_filter:
                        continue
                filtered_users.append(u)
            
            if not filtered_users:
                continue
                
            total_missing += len(filtered_users)
            
            # 为此项目准备用户列表
            user_list = []
            for u in filtered_users:
                user_list.append({
                    'name': u.get_full_name() or u.username,
                    'last_date': last_map.get(u.id)
                })
                
            missing_projects.append({
                'project': p.name,
                'project_id': p.id,
                'missing_count': len(filtered_users),
                'users': user_list,
                'last_map': {u.id: last_map.get(u.id) for u in filtered_users} # 如果需要，用于个人提醒
            })
            
        cache.set(cache_key, (missing_projects, total_missing), 300)

    # 一键催报（立即邮件通知）
    if request.GET.get('remind') == '1' and missing_projects:
        notified = 0
        usernames = []
        for item in missing_projects:
            for u in get_user_model().objects.filter(id__in=item['last_map'].keys()):
                if u.email:
                    subject = f"[催报提醒] {target_date} 日报未提交"
                    body = (
                        f"{u.get_full_name() or u.username}，您好：\n\n"
                        f"项目：{item['project']} 日报未提交。\n"
                        f"请尽快补交 {target_date} 的日报。如已提交请忽略。\n"
                    )
                    send_mail(subject, body, None, [u.email], fail_silently=True)
                    notified += 1
                    usernames.append(u.username)
        log_action(request, 'update', f"remind_missing date={target_date}", data={'users': usernames})
        if notified:
            messages.success(request, f"已发送催报邮件 {notified} 封")
        else:
            messages.info(request, "暂无可发送邮件的缺报用户")

    tasks_qs = Task.objects.all()
    tasks_missing_due = tasks_qs.filter(due_at__isnull=True).count()
    cached_stats = cache.get(cache_key_metrics)
    if cached_stats:
        metrics, role_counts, top_projects, project_sla_stats, overdue_top, generated_at = cached_stats
    else:
        projects = Project.objects.filter(is_active=True).order_by('name').annotate(
            total=Count('tasks'),
            completed=Count('tasks', filter=Q(tasks__status=TaskStatus.DONE)),
            overdue=Count('tasks', filter=Q(tasks__status='overdue')),
            within_sla=Count('tasks', filter=Q(
                tasks__status=TaskStatus.DONE,
                tasks__due_at__isnull=False,
                tasks__completed_at__isnull=False,
                tasks__completed_at__lte=F('tasks__due_at')
            ))
        )
        
        project_sla_stats = []
        for p in projects:
            total = p.total
            completed = p.completed
            overdue = p.overdue
            within_sla = p.within_sla
            
            sla_rate = (within_sla / completed * 100) if completed else 0
            project_sla_stats.append({
                'project': p,
                'total': total,
                'completed': completed,
                'overdue': overdue,
                'within_sla': within_sla,
                'sla_rate': sla_rate,
            })

        overdue_top = tasks_qs.filter(status='overdue').select_related('project', 'user').order_by('-due_at')[:10]

        metrics = {
            'total_reports': qs.count(),
            'total_projects': Project.objects.filter(is_active=True).count(),
            'active_users': qs.values('user').distinct().count(),
            'last_date': qs.order_by('-date').first().date if qs.exists() else None,
            'missing_today': total_missing,
            'tasks_missing_due': tasks_missing_due,
        }
        role_counts = qs.values_list('role').annotate(c=Count('id')).order_by('-c')
        top_projects = Project.objects.filter(is_active=True).annotate(report_count=Count('reports')).order_by('-report_count')[:5]
        cache.set(cache_key_metrics, (metrics, role_counts, top_projects, project_sla_stats, overdue_top, generated_at), 600)
    sla_urgent_tasks = []
    
    # 预取 SLA 设置一次
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None

    for t in Task.objects.select_related('project', 'user', 'sla_timer').exclude(status__in=[TaskStatus.DONE, TaskStatus.CLOSED]).iterator():
        info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
        if info and info.get('status') in ('tight', 'overdue'):
            t.sla_info = info
            sla_urgent_tasks.append(t)
    sla_urgent_tasks.sort(key=lambda t: (
        t.sla_info.get('sort', 3),
        t.sla_info.get('remaining_hours') if t.sla_info.get('remaining_hours') is not None else 9999,
        -t.created_at.timestamp(),
    ))

    return render(request, 'reports/stats.html', {
        'metrics': metrics,
        'role_counts': role_counts,
        'top_projects': top_projects,
        'missing_projects': missing_projects,
        'today': target_date,
        'sla_remind': get_sla_hours(system_setting_value=sla_hours_val),
        'sla_thresholds': thresholds,
        'project_sla_stats': project_sla_stats,
        'overdue_top': overdue_top,
        'project_filter': int(project_filter) if project_filter and project_filter.isdigit() else '',
        'role_filter': role_filter,
        'report_roles': Profile.ROLE_CHOICES,
        'projects': Project.objects.filter(is_active=True).order_by('name'),
        'generated_at': generated_at,
        'sla_only': sla_only,
        'sla_urgent_tasks': sla_urgent_tasks,
    })


@login_required
def performance_board(request):
    """绩效与统计看板：项目/角色完成率、逾期率、连签趋势，可触发周报邮件。"""
    accessible_projects = None
    
    if request.user.is_superuser:
        projects_qs = Project.objects.filter(is_active=True).order_by('name').only('id', 'name')
    else:
        # 普通用户：检查他们是否可以看到任何绩效统计数据
        # 需求：“管理报告”页面 -> 细粒度。
        # 如果我是 P1 的经理，我可以看到 P1 的统计数据。
        accessible_projects = get_accessible_projects(request.user)
        if not accessible_projects.exists():
            messages.error(request, "需要管理员权限 / Admin access required")
            return render(request, '403.html', status=403)
        projects_qs = accessible_projects.order_by('name').only('id', 'name')

    start_date = parse_date(request.GET.get('start') or '') or None
    end_date = parse_date(request.GET.get('end') or '') or None
    project_param = request.GET.get('project')
    role_param = (request.GET.get('role') or '').strip()
    q = request.GET.get('q')
    project_filter = int(project_param) if project_param and project_param.isdigit() else None
    role_filter = role_param if role_param in dict(Profile.ROLE_CHOICES) else None

    # 项目过滤器的安全检查
    if project_filter and accessible_projects is not None:
        if not accessible_projects.filter(id=project_filter).exists():
             return _admin_forbidden(request, "没有该项目的访问权限 / No access to this project")

    # 统计数据缓存键
    cache_key = f"perf_board_stats_{request.user.id}_{start_date}_{end_date}_{project_filter}_{role_filter}_{q}"
    stats = cache.get(cache_key)
    
    if not stats:
        stats = _performance_stats(
            start_date=start_date, 
            end_date=end_date, 
            project_id=project_filter, 
            role_filter=role_filter, 
            q=q,
            accessible_projects=accessible_projects
        )
        cache.set(cache_key, stats, 600) # 缓存 10 分钟
    
    # 根据权限过滤紧急任务
    urgent_tasks = 0
    total_tasks = 0
    
    if 'overall_overdue' in stats:
        urgent_tasks = stats['overall_overdue']
    else:
        urgent_tasks_qs = Task.objects.filter(status='overdue')
        if accessible_projects is not None:
            urgent_tasks_qs = urgent_tasks_qs.filter(project__in=accessible_projects)
        urgent_tasks = urgent_tasks_qs.count()

    if 'overall_total' in stats:
        total_tasks = stats['overall_total']
    else:
        total_tasks_qs = Task.objects.all()
        if accessible_projects is not None:
            total_tasks_qs = total_tasks_qs.filter(project__in=accessible_projects)
        total_tasks = total_tasks_qs.count()
    
    # 预取 SLA 设置一次
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
    
    thresholds = get_sla_thresholds(system_setting_value=sla_thresholds_val)
    sla_only = request.GET.get('sla_only') == '1'
    
    # 构造项目燃尽图数据 (用于前端 Chart.js，避免二次请求)
    project_data = stats.get('project_stats', [])
    chart_data = {
        'labels': [p['project'] for p in project_data], # 注意：这里用 'project' 而不是 'name'，取决于 stats.py 的键名
        'datasets': [
            {'label': '已完成', 'data': [p['completed'] for p in project_data], 'backgroundColor': '#10b981'},
            {'label': '剩余', 'data': [p['total'] - p['completed'] for p in project_data], 'backgroundColor': '#3b82f6'},
            {'label': '逾期', 'data': [p['overdue'] for p in project_data], 'backgroundColor': '#ef4444'},
        ],
        'overall_rate': stats.get('overall_sla_on_time_rate', 0)
    }

    # 紧急任务计算较慢，增加缓存
    sla_cache_key = f"perf_board_sla_{request.user.id}_{project_filter}_{sla_hours_val}"
    sla_urgent_tasks = cache.get(sla_cache_key)
    
    if sla_urgent_tasks is None:
        sla_urgent_tasks = []
        
        # 优化：select_related 'sla_timer' 以避免 calculate_sla_info 中的 N+1
        # 优化：过滤潜在的紧急任务以减少 Python 处理
        max_threshold = thresholds.get('amber', 4)
        # 保守策略：检查在 (阈值 + 1h) 内到期或很久以前创建的任务
        cutoff = timezone.now() + timedelta(hours=max_threshold + 1)
        
        sla_qs = Task.objects.select_related('project', 'user', 'sla_timer').exclude(
            status__in=[TaskStatus.DONE, TaskStatus.CLOSED]
        )
        
        if accessible_projects is not None:
            sla_qs = sla_qs.filter(project__in=accessible_projects)
        
        # 过滤器：要么有 due_at <= cutoff，要么（无 due_at 且 created_at <= cutoff - default_sla）
        # 如果存在特定项目的 SLA，我们在不进行复杂查询的情况下无法轻易过滤，因此通过 OR 包含它们
        
        default_sla = sla_hours_val or 48 # 如果设置缺失，默认为 48
        created_cutoff = cutoff - timedelta(hours=default_sla)
        
        # 优化：仅查询必要字段
        sla_qs = sla_qs.filter(
            Q(due_at__lte=cutoff) | 
            (Q(due_at__isnull=True) & Q(project__sla_hours__isnull=True) & Q(created_at__lte=created_cutoff)) |
            (Q(due_at__isnull=True) & Q(project__sla_hours__isnull=False)) # 为安全起见保留项目 SLA 任务
        ).only('id', 'title', 'due_at', 'created_at', 'status', 'project', 'user', 'sla_timer')
            
        for t in sla_qs:
            # 传递解析后的阈值字典而不是原始字符串
            info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=thresholds)
            if info and info.get('status') in ('tight', 'overdue'):
                t.sla_info = info
                sla_urgent_tasks.append(t)
        sla_urgent_tasks.sort(key=lambda t: (
            t.sla_info.get('sort', 3),
            t.sla_info.get('remaining_hours') if t.sla_info.get('remaining_hours') is not None else 9999,
            -t.created_at.timestamp(),
        ))
        
        # 缓存 5 分钟
        cache.set(sla_cache_key, sla_urgent_tasks, 300)

    if request.GET.get('send_weekly') == '1':
        # Send weekly logic... (keep as is)
        # 发送周报逻辑...（保持原样）
        recipient = (request.user.email or '').strip()
        if not recipient:
            messages.error(request, "请先在个人中心绑定邮箱 / Please bind email first.")
        else:
            sent = _send_weekly_digest(recipient, stats)
            if sent:
                messages.success(request, "周报已发送到绑定邮箱 / Weekly digest sent.")
            else:
                messages.error(request, "周报发送失败，请稍后再试 / Weekly digest failed.")

    return render(request, 'reports/performance_board.html', {
        **stats,
        'urgent_tasks': urgent_tasks,
        'total_tasks': total_tasks,
        'sla_thresholds': thresholds,
        'sla_only': sla_only,
        'sla_urgent_tasks': sla_urgent_tasks,
        'start': start_date,
        'end': end_date,
        'project_filter': project_filter,
        'role_filter': role_filter,
        'projects': projects_qs,
        'report_roles': Profile.ROLE_CHOICES,
        'user_stats_page': Paginator(stats.get('user_stats', []), 10).get_page(request.GET.get('upage')),
        'chart_data': json.dumps(chart_data), # 注入 JSON 字符串
    })
