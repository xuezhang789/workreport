from django.contrib.auth import login, logout, get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import models, transaction
from django.db.models import Q, Count
import os
import logging

from django.http import HttpResponse, StreamingHttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib import messages

import csv
import time
import json
import re
import random
from io import StringIO
from datetime import datetime, timedelta
from django.db import models

from .forms import (
    ProjectForm,
    RegistrationForm,
    PasswordUpdateForm,
    UsernameUpdateForm,
    EmailVerificationRequestForm,
    EmailVerificationConfirmForm,
    ReportTemplateForm,
    TaskTemplateForm,
    ProjectPhaseConfigForm,
)
from .models import AuditLog, DailyReport, Profile, Project, Task, TaskComment, TaskAttachment, RoleTemplate, SystemSetting, TaskHistory, TaskSlaTimer, ReportTemplateVersion, TaskTemplateVersion, ExportJob, ProjectPhaseConfig, ProjectPhaseChangeLog, ProjectAttachment
from .signals import _invalidate_stats_cache
from django.conf import settings
from .services.sla import calculate_sla_info, get_sla_thresholds, get_sla_hours
from .services.stats import get_performance_stats as _performance_stats

MENTION_PATTERN = re.compile(r'@([\\w.@+-]+)')
logger = logging.getLogger(__name__)


MANAGER_ROLES = {'mgr', 'pm'}
MAX_EXPORT_ROWS = 5000
EXPORT_CHUNK_SIZE = 500
DEFAULT_SLA_REMIND = getattr(settings, 'SLA_REMIND_HOURS', 24)


def has_manage_permission(user):
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    try:
        return user.profile.position in MANAGER_ROLES
    except Profile.DoesNotExist:
        return False


def log_action(request, action: str, extra: str = "", data=None):
    ip = request.META.get('REMOTE_ADDR')
    ua = request.META.get('HTTP_USER_AGENT', '')[:512]
    elapsed_ms = getattr(request, '_elapsed_ms', None)
    if elapsed_ms is None and hasattr(request, '_elapsed_start'):
        elapsed_ms = int((time.monotonic() - request._elapsed_start) * 1000)
    AuditLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        action=action,
        path=request.path[:255],
        method=request.method,
        ip=ip,
        extra=extra[:2000],
        data={
            **(data or {}),
            'ua': ua,
            **({'elapsed_ms': elapsed_ms} if elapsed_ms is not None else {}),
        },
    )


def _throttle(request, key: str, min_interval=0.8):
    """简单接口节流，基于 session/key。"""
    now = time.monotonic()
    last = request.session.get(key)
    if last and now - last < min_interval:
        return True
    request.session[key] = now
    return False


def _admin_forbidden(request, message="需要管理员权限 / Admin access required"):
    messages.error(request, message)
    return render(request, '403.html', {'detail': message}, status=403)


def _friendly_forbidden(request, message):
    """统一的友好 403 返回，带双语提示。"""
    return render(request, '403.html', {'detail': message}, status=403)


def _notify(request, users, message, category="info"):
    """
    简易通知闭环：写入审计日志，并可扩展为邮件/Webhook。
    """
    usernames = [u.username for u in users]
    log_action(request, 'update', f"notify[{category}] {message}", data={'users': usernames})


def _add_history(task: Task, user, field: str, old: str, new: str):
    if str(old) == str(new):
        return
    TaskHistory.objects.create(task=task, user=user if user and user.is_authenticated else None, field=field, old_value=str(old or ''), new_value=str(new or ''))


def _mask_email(email: str) -> str:
    if '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"


def has_project_manage_permission(user, project: Project):
    if has_manage_permission(user):
        return True
    if project.owner_id == user.id:
        return True
    # Optimization: Use prefetch cache if available to avoid N+1 queries
    if hasattr(project, '_prefetched_objects_cache') and 'managers' in project._prefetched_objects_cache:
        return any(m.id == user.id for m in project.managers.all())
    return project.managers.filter(id=user.id).exists()


def _streak_map():
    """计算用户连签天数字典，键为 user_id。优化性能，使用Django ORM高效查询"""
    from django.db.models import Max
    from django.db.models.functions import RowNumber
    from django.db.models import Window
    
    # 获取所有提交的报告，按用户和日期排序
    submissions = DailyReport.objects.filter(
        status='submitted'
    ).order_by('user_id', 'date').values('user_id', 'date')
    
    # 构建每个用户的日期集合
    user_dates = {}
    for item in submissions:
        user_dates.setdefault(item['user_id'], set()).add(item['date'])
    
    today = timezone.localdate()
    streaks = {}
    
    # 对每个用户计算连签天数
    for uid, dates in user_dates.items():
        if not dates:
            streaks[uid] = 0
            continue
            
        # 从今天开始倒推，计算连续日期的数量
        curr = today
        streak = 0
        while curr in dates:
            streak += 1
            curr = curr - timedelta(days=1)
        streaks[uid] = streak
    
    return streaks


def _filtered_reports(request):
    """Return filtered queryset plus filter values."""
    role = (request.GET.get('role') or '').strip()
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')

    qs = DailyReport.objects.select_related('user').prefetch_related('projects').order_by('-date', '-created_at')
    if role:
        qs = qs.filter(role=role)
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    return qs, role, start_date, end_date


def _build_sections(report):
    return {
        'dev': [
            ('今日完成工作 / Work Completed Today', report.today_work),
            ('今日进展 & 问题 / Progress & Issues', report.progress_issues),
            ('明日工作计划 / Plan for Tomorrow', report.tomorrow_plan),
        ],
        'qa': [
            ('今日测试范围 / Today’s Testing Scope', report.testing_scope),
            ('测试完成情况 / Testing Progress', report.testing_progress),
            ('Bug 统计 / Bug Summary', report.bug_summary),
            ('明日测试计划 / Plan for Tomorrow', report.testing_tomorrow),
        ],
        'pm': [
            ('今日产品推进内容 / Product Progress Today', report.product_today),
            ('今日协调 / 决策事项 / Coordination & Decisions', report.product_coordination),
            ('明日计划 / Plan for Tomorrow', report.product_tomorrow),
        ],
        'ui': [
            ('今日完成设计 / Designs Completed Today', report.ui_today),
            ('反馈与修改 / Feedback & Revisions', report.ui_feedback),
            ('明日计划 / Plan for Tomorrow', report.ui_tomorrow),
        ],
        'ops': [
            ('今日运维工作 / Operations Tasks Today', report.ops_today),
            ('监控与故障情况 / Monitoring & Incidents', report.ops_monitoring),
            ('明日计划 / Plan for Tomorrow', report.ops_tomorrow),
        ],
        'mgr': [
            ('今日项目进度概览 / Project Progress Overview', report.mgr_progress),
            ('风险与阻塞点 / Risks & Blockers', report.mgr_risks),
            ('明日推进重点 / Key Focus for Tomorrow', report.mgr_tomorrow),
        ],
    }.get(report.role, [])


def _has_role_content(role: str, payload: dict) -> bool:
    role_fields = {
        'dev': ['today_work', 'progress_issues', 'tomorrow_plan'],
        'qa': ['testing_scope', 'testing_progress', 'bug_summary', 'testing_tomorrow'],
        'pm': ['product_today', 'product_coordination', 'product_tomorrow'],
        'ui': ['ui_today', 'ui_feedback', 'ui_tomorrow'],
        'ops': ['ops_today', 'ops_monitoring', 'ops_tomorrow'],
        'mgr': ['mgr_progress', 'mgr_risks', 'mgr_tomorrow'],
    }
    fields = role_fields.get(role, [])
    return any((payload.get(f, '') or '').strip() for f in fields)


CSV_DANGEROUS_PREFIXES = ('=', '+', '-', '@', '\t')


def _sanitize_csv_cell(value):
    if value is None:
        return ''
    text = str(value)
    if text.startswith(CSV_DANGEROUS_PREFIXES):
        return "'" + text
    return text


def _stream_csv(rows, header):
    def generate():
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow([_sanitize_csv_cell(h) for h in header])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for row in rows:
            writer.writerow([_sanitize_csv_cell(col) for col in row])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
    return generate()


def _create_export_job(user, export_type):
    expires = timezone.now() + timedelta(days=3)
    return ExportJob.objects.create(user=user, export_type=export_type, status='running', progress=10, expires_at=expires)


def _generate_export_file(job, header, rows_iterable):
    """生成 CSV 临时文件，更新 Job 状态，返回文件路径。"""
    import tempfile
    import csv as pycsv
    import os
    fd, path = tempfile.mkstemp(prefix=f'export_{job.export_type}_', suffix='.csv')
    with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
        writer = pycsv.writer(f)
        writer.writerow([_sanitize_csv_cell(h) for h in header])
        total = 0
        for total, row in enumerate(rows_iterable, start=1):
            writer.writerow([_sanitize_csv_cell(col) for col in row])
            if total % 50 == 0:
                job.progress = min(95, job.progress + 5)
                job.save(update_fields=['progress', 'updated_at'])
        job.progress = 100
        job.status = 'done'
        job.file_path = path
        job.save(update_fields=['status', 'progress', 'file_path', 'updated_at'])
    return path


def _report_initial(report: DailyReport | None):
    if not report:
        return {}
    return {
        'date': report.date,
        'role': report.role,
        'today_work': report.today_work,
        'progress_issues': report.progress_issues,
        'tomorrow_plan': report.tomorrow_plan,
        'testing_scope': report.testing_scope,
        'testing_progress': report.testing_progress,
        'bug_summary': report.bug_summary,
        'testing_tomorrow': report.testing_tomorrow,
        'product_today': report.product_today,
        'product_coordination': report.product_coordination,
        'product_tomorrow': report.product_tomorrow,
        'ui_today': report.ui_today,
        'ui_feedback': report.ui_feedback,
        'ui_tomorrow': report.ui_tomorrow,
        'ops_today': report.ops_today,
        'ops_monitoring': report.ops_monitoring,
        'ops_tomorrow': report.ops_tomorrow,
        'mgr_progress': report.mgr_progress,
        'mgr_risks': report.mgr_risks,
        'mgr_tomorrow': report.mgr_tomorrow,
        'status': report.status,
    }


def _filtered_projects(request):
    q = (request.GET.get('q') or '').strip()
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    owner = (request.GET.get('owner') or '').strip()

    # 按创建时间倒序展示，确保最近的项目排在前面
    qs = Project.objects.select_related('owner', 'current_phase').prefetch_related('members', 'reports', 'managers').filter(is_active=True).order_by('-created_at', '-id')
    if not has_manage_permission(request.user):
        qs = qs.filter(Q(owner=request.user) | Q(members=request.user) | Q(managers=request.user))
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
    if start_date:
        qs = qs.filter(Q(start_date__gte=start_date) | Q(start_date__isnull=True))
    if end_date:
        qs = qs.filter(Q(end_date__lte=end_date) | Q(end_date__isnull=True))
    if owner:
        qs = qs.filter(Q(owner__username__icontains=owner) | Q(owner__first_name__icontains=owner) | Q(owner__last_name__icontains=owner))
    return qs, q, start_date, end_date, owner


@login_required
def role_template_api(request):
    """返回角色模板占位与提示，供前端加载。"""
    role = (request.GET.get('role') or '').strip()
    if role not in dict(Profile.ROLE_CHOICES):
        return JsonResponse({'error': 'invalid role'}, status=400)
    tmpl = RoleTemplate.objects.filter(role=role, is_active=True).order_by('sort_order', '-updated_at').first()
    if not tmpl:
        return JsonResponse({'placeholders': {}, 'hint': ''})
    return JsonResponse({
        'placeholders': tmpl.placeholders or {},
        'hint': tmpl.hint or '',
        'sample_md': tmpl.sample_md or '',
        'updated_at': tmpl.updated_at.isoformat(),
    })


@login_required
def project_search_api(request):
    """项目远程搜索，支持常用项目置顶。"""
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    if _throttle(request, 'project_search_ts'):
        return JsonResponse({'error': '请求过于频繁'}, status=429)
    q = (request.GET.get('q') or '').strip()
    project_filter = Q(is_active=True)
    user = request.user
    if not has_manage_permission(user):
        project_filter &= (Q(members=user) | Q(managers=user) | Q(owner=user))
    qs = Project.objects.filter(project_filter).annotate(
        user_used=Count('reports', filter=Q(reports__user=user))
    )
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
    projects = qs.order_by('-user_used', 'name')[:20]
    data = [{'id': p.id, 'name': p.name, 'code': p.code} for p in projects]
    return JsonResponse({'results': data})


@login_required
def user_search_api(request):
    """人员远程搜索，用于任务指派等场景。"""
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    if _throttle(request, 'user_search_ts'):
        return JsonResponse({'error': '请求过于频繁'}, status=429)
    q = (request.GET.get('q') or '').strip()
    User = get_user_model()
    qs = User.objects.all()
    if q:
        qs = qs.filter(
            Q(username__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )
    users = qs.order_by('username')[:20]
    data = [{'id': u.id, 'name': u.get_full_name() or u.username, 'username': u.username} for u in users]
    return JsonResponse({'results': data})


@login_required
def username_check_api(request):
    """实时检查用户名是否可用。"""
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    if _throttle(request, 'username_check_ts', min_interval=0.4):
        return JsonResponse({'error': '请求过于频繁'}, status=429)  # 简易节流防抖
    username = (request.GET.get('username') or '').strip()
    if not username:
        return JsonResponse({'available': False, 'reason': '请输入要检测的用户名 / Please enter a username to check'}, status=400)
    UserModel = get_user_model()
    exists = UserModel.objects.filter(username__iexact=username).exclude(pk=request.user.pk).exists()
    return JsonResponse({'available': not exists})


@login_required
def workbench(request):
    # 获取用户任务统计 (优化：使用聚合查询代替多次 count)
    from django.db.models import Count, Q
    
    tasks = Task.objects.filter(user=request.user)
    
    stats = tasks.aggregate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='completed')),
        overdue=Count('id', filter=Q(status='overdue')),
        in_progress=Count('id', filter=Q(status='in_progress')),
        pending=Count('id', filter=Q(status='pending'))
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
    today_tasks_count = tasks.filter(due_at__date=today.date()).exclude(status='completed').count()
    upcoming_tasks_count = tasks.filter(
        due_at__date__gt=today.date(),
        due_at__date__lte=today.date() + timedelta(days=3)
    ).exclude(status='completed').count()

    # daily report streak and today's report status
    today_date = timezone.localdate()
    qs_reports = DailyReport.objects.filter(user=request.user, status='submitted').values_list('date', flat=True).order_by('-date')
    date_set = set(qs_reports)
    streak = 0
    curr = today_date
    while curr in date_set:
        streak += 1
        curr = curr - timedelta(days=1)
    
    # 检查今日是否已提交日报
    today_report = DailyReport.objects.filter(user=request.user, date=today_date).first()
    has_today_report = today_report is not None and today_report.status == 'submitted'

    # project burndown with enhanced data
    projects = Project.objects.filter(is_active=True, tasks__user=request.user).distinct().annotate(
        total_p=Count('tasks', filter=Q(tasks__user=request.user)),
        completed_p=Count('tasks', filter=Q(tasks__user=request.user, tasks__status='completed')),
        overdue_p=Count('tasks', filter=Q(tasks__user=request.user, tasks__status='overdue')),
        in_progress_p=Count('tasks', filter=Q(tasks__user=request.user, tasks__status='in_progress'))
    )
    
    project_burndown = []
    for proj in projects:
        total_p = proj.total_p
        completed_p = proj.completed_p
        overdue_p = proj.overdue_p
        in_progress_p = proj.in_progress_p
        completion_rate_p = (completed_p / total_p * 100) if total_p else 0
        
        project_burndown.append({
            'project': proj.name,
            'code': proj.code,
            'total': total_p,
            'completed': completed_p,
            'in_progress': in_progress_p,
            'remaining': total_p - completed_p,
            'overdue': overdue_p,
            'completion_rate': completion_rate_p,
        })

    # recent reports with status
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


def generate_workbench_guidance(total, completed, overdue, in_progress, pending, streak, has_today_report, user_role, today_tasks_count, upcoming_tasks_count):
    """生成智能工作台引导文案"""
    completion_rate = (completed / total * 100) if total else 0
    
    guidance = {
        'primary': '',
        'secondary': '',
        'actions': [],
        'status': 'normal'
    }
    
    # 根据不同情况生成主要引导文案
    if not has_today_report:
        if user_role == 'dev':
            guidance['primary'] = "📝 今日待提交 / Today's Report Pending"
            guidance['secondary'] = "记录今日开发进展，为团队协作提供透明度 / Log today's development progress for team transparency"
        elif user_role == 'qa':
            guidance['primary'] = "🧪 测试日报待填写 / QA Report Pending"
            guidance['secondary'] = "记录测试范围和发现的问题，确保产品质量 / Document testing scope and issues found for quality assurance"
        elif user_role == 'pm':
            guidance['primary'] = "📋 产品日报待提交 / Product Report Pending"
            guidance['secondary'] = "同步产品进展和协调事项，推动项目前进 / Sync product progress and coordination to drive projects forward"
        else:
            guidance['primary'] = "📊 工作日报待填写 / Work Report Pending"
            guidance['secondary'] = "分享今日工作成果，让团队了解你的贡献 / Share today's work achievements and let the team know your contributions"
        guidance['status'] = 'urgent'
        guidance['actions'].append({
            'text': '立即提交日报 / Submit Report',
            'url': 'reports:daily_report_create',
            'priority': 'high'
        })
    
    # 任务相关引导
    elif overdue > 0:
        guidance['primary'] = "⚠️ 有逾期任务需要处理 / Overdue Tasks Need Attention"
        guidance['secondary'] = f"您有 {overdue} 个任务已逾期，请及时处理以避免项目延期 / You have {overdue} overdue tasks, please handle them promptly to avoid project delays"
        guidance['status'] = 'warning'
        guidance['actions'].append({
            'text': '查看逾期任务 / View Overdue Tasks',
            'url': 'reports:task_list',
            'priority': 'high'
        })
    
    elif today_tasks_count > 0:
        guidance['primary'] = "🎯 今日任务待完成 / Today's Tasks Pending"
        guidance['secondary'] = f"您有 {today_tasks_count} 个任务今日到期，专注完成这些任务 / You have {today_tasks_count} tasks due today, focus on completing these tasks"
        guidance['status'] = 'normal'
        guidance['actions'].append({
            'text': '查看今日任务 / View Today\'s Tasks',
            'url': 'reports:task_list',
            'priority': 'medium'
        })
    
    elif upcoming_tasks_count > 0:
        guidance['primary'] = "📅 即将到期任务 / Upcoming Deadlines"
        guidance['secondary'] = f"您有 {upcoming_tasks_count} 个任务将在3天内到期，提前规划时间 / You have {upcoming_tasks_count} tasks due in 3 days, plan your time in advance"
        guidance['status'] = 'normal'
    
    elif in_progress > 0:
        guidance['primary'] = "🚀 任务进行中 / Tasks in Progress"
        guidance['secondary'] = f"您有 {in_progress} 个任务正在进行中，保持专注完成 / You have {in_progress} tasks in progress, stay focused to complete them"
        guidance['status'] = 'normal'
    
    elif total == 0:
        guidance['primary'] = "🌟 开始新任务 / Start New Tasks"
        guidance['secondary'] = "当前没有分配的任务，可以主动申请新任务或创建个人任务 / No tasks assigned currently, you can proactively apply for new tasks or create personal tasks"
        guidance['status'] = 'info'
        guidance['actions'].append({
            'text': '查看所有项目 / View All Projects',
            'url': 'reports:project_list',
            'priority': 'low'
        })
    
    # 连签激励
    if streak >= 7:
        guidance['secondary'] += f" 🔥 连续提交日报 {streak} 天，继续保持！/ {streak} days streak, keep it up!"
    elif streak >= 3:
        guidance['secondary'] += f" 📈 连续提交日报 {streak} 天，很棒的坚持！/ {streak} days streak, great consistency!"
    
    # 完成率激励
    if total > 0 and completion_rate >= 80:
        guidance['secondary'] += f" ✅ 任务完成率 {completion_rate:.1f}%，表现优秀！/ Task completion rate {completion_rate:.1f}%, excellent performance!"
    
    return guidance


@login_required
def role_template_manage(request):
    """管理员配置角色模板占位和提示语。"""
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    selected_role = (request.POST.get('role') or request.GET.get('role') or 'dev').strip()
    message = ''
    error = ''
    hint_text = ''
    sample_text = ''
    placeholders_text = ''
    updated_at = None
    is_active = True
    sort_order_value = '0'
    role_fields = {
        'dev': ['today_work', 'progress_issues', 'tomorrow_plan'],
        'qa': ['testing_scope', 'testing_progress', 'bug_summary', 'testing_tomorrow'],
        'pm': ['product_today', 'product_coordination', 'product_tomorrow'],
        'ui': ['ui_today', 'ui_feedback', 'ui_tomorrow'],
        'ops': ['ops_today', 'ops_monitoring', 'ops_tomorrow'],
        'mgr': ['mgr_progress', 'mgr_risks', 'mgr_tomorrow'],
    }

    existing = RoleTemplate.objects.filter(role=selected_role).first()
    if existing:
        hint_text = existing.hint or ''
        sample_text = existing.sample_md or ''
        placeholders_text = json.dumps(existing.placeholders or {}, ensure_ascii=False, indent=2)
        updated_at = existing.updated_at
        is_active = existing.is_active
        sort_order_value = str(existing.sort_order)

    if request.method == 'POST':
        hint_text = request.POST.get('hint') or ''
        sample_text = request.POST.get('sample_md') or ''
        is_active = request.POST.get('is_active') == 'on'
        sort_order_value = request.POST.get('sort_order') or '0'
        # 长度限制，避免过长示例影响加载
        if len(hint_text) > 2000:
            error = "提示语过长（上限 2000 字）"
        if len(sample_text) > 4000:
            error = "示例过长（上限 4000 字）"
        try:
            sort_order_int = int(sort_order_value)
        except ValueError:
            sort_order_int = 0
        placeholders_text = request.POST.get('placeholders') or ''
        try:
            placeholders = json.loads(placeholders_text) if placeholders_text.strip() else {}
            if not isinstance(placeholders, dict):
                raise ValueError("占位应为 JSON 对象")
        except Exception as exc:
            error = f"占位 JSON 解析失败：{exc}"
        if not error:
            tmpl, _ = RoleTemplate.objects.update_or_create(
                role=selected_role,
                defaults={
                    'hint': hint_text,
                    'placeholders': placeholders,
                    'sample_md': sample_text,
                    'is_active': is_active,
                    'sort_order': sort_order_int,
                }
            )
            message = "模板已保存"
            _invalidate_stats_cache()
            hint_text = tmpl.hint or ''
            sample_text = tmpl.sample_md or ''
            placeholders_text = json.dumps(tmpl.placeholders or {}, ensure_ascii=False, indent=2)

    return render(request, 'reports/role_templates.html', {
        'selected_role': selected_role,
        'hint_text': hint_text,
        'sample_text': sample_text,
        'placeholders_text': placeholders_text,
        'updated_at': updated_at,
        'roles': Profile.ROLE_CHOICES,
        'message': message,
        'error': error,
        'current_fields': role_fields.get(selected_role, []),
        'is_active': is_active,
        'sort_order_value': sort_order_value,
    })


@login_required
def template_center(request):
    """模板中心：保存日报/任务模板，按项目/角色共享并保留版本。"""
    if not has_manage_permission(request.user):
        messages.error(request, "需要管理员权限 / Admin access required")
        return render(request, '403.html', status=403)

    report_form = ReportTemplateForm()
    task_form = TaskTemplateForm()
    q = (request.GET.get('q') or '').strip()
    role_filter = (request.GET.get('role') or '').strip()
    project_filter = request.GET.get('project')
    tpl_type = (request.GET.get('type') or '').strip()
    sort = (request.GET.get('sort') or 'version').strip()  # version|updated|usage

    def _latest_versions(qs):
        seen = set()
        latest = []
        order_fields = ['name', 'project_id', 'role', '-version']
        if sort == 'updated':
            order_fields = ['name', 'project_id', 'role', '-created_at', '-version']
        if sort == 'usage':
            order_fields = ['name', 'project_id', 'role', '-usage_count', '-created_at', '-version']
        for item in qs.order_by(*order_fields):
            key = (item.name, item.project_id, item.role)
            if key not in seen:
                seen.add(key)
                latest.append(item)
        return latest

    report_qs = ReportTemplateVersion.objects.select_related('project', 'created_by').all()
    task_qs = TaskTemplateVersion.objects.select_related('project', 'created_by').all()
    if role_filter:
        report_qs = report_qs.filter(role=role_filter)
        task_qs = task_qs.filter(role=role_filter)
    if project_filter and project_filter.isdigit():
        pid = int(project_filter)
        report_qs = report_qs.filter(project_id=pid)
        task_qs = task_qs.filter(project_id=pid)
    if q:
        report_qs = report_qs.filter(Q(name__icontains=q) | Q(content__icontains=q))
        task_qs = task_qs.filter(Q(name__icontains=q) | Q(title__icontains=q) | Q(content__icontains=q))

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'report':
            report_form = ReportTemplateForm(request.POST)
            if report_form.is_valid():
                tmpl = report_form.save(created_by=request.user)
                messages.success(request, f"日报模板已保存 v{tmpl.version} / Report template saved.")
                _invalidate_stats_cache()
                return redirect('reports:template_center')
        elif action == 'task':
            task_form = TaskTemplateForm(request.POST)
            if task_form.is_valid():
                tmpl = task_form.save(created_by=request.user)
                messages.success(request, f"任务模板已保存 v{tmpl.version} / Task template saved.")
                _invalidate_stats_cache()
                return redirect('reports:template_center')

    report_latest = _latest_versions(report_qs)
    task_latest = _latest_versions(task_qs)
    report_page = Paginator(report_latest, 10).get_page(request.GET.get('rpage'))
    task_page = Paginator(task_latest, 10).get_page(request.GET.get('tpage'))

    return render(request, 'reports/template_center.html', {
        'report_form': report_form,
        'task_form': task_form,
        'report_templates': report_page,
        'task_templates': task_page,
        'q': q,
        'role_filter': role_filter,
        'project_filter': int(project_filter) if project_filter and project_filter.isdigit() else '',
        'projects': Project.objects.filter(is_active=True).order_by('name'),
        'sort': sort,
    })


@login_required
def template_apply_api(request):
    """一键套用模板：按 type=report|task + role + project 获取最新共享版本。"""
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    tpl_type = (request.GET.get('type') or 'report').strip()
    role = (request.GET.get('role') or '').strip() or None
    project_ids = request.GET.getlist('project') or [request.GET.get('project')]
    name = (request.GET.get('name') or '').strip() or None
    projects = []
    for pid in project_ids:
        if pid and str(pid).isdigit():
            proj = Project.objects.filter(id=int(pid)).first()
            if proj:
                projects.append(proj)

    def qs_for(model):
        q = Q(is_shared=True)
        if request.user.is_authenticated:
            q |= Q(created_by=request.user)
        qs = model.objects.filter(q)
        if role:
            qs = qs.filter(role=role)
        if name:
            qs = qs.filter(name=name)
        return qs

    if tpl_type == 'task':
        qs = qs_for(TaskTemplateVersion)
        primary = qs.filter(project__in=projects) if projects else qs
        tmpl = primary.order_by('-version', '-created_at').first()
        fallback = False
        if not tmpl and role:
            fallback_qs = qs.filter(project__isnull=True)
            tmpl = fallback_qs.order_by('-version', '-created_at').first()
            fallback = bool(tmpl)
        if not tmpl:
            return JsonResponse({'error': 'no task template'}, status=404)
        tmpl.usage_count = (tmpl.usage_count or 0) + 1
        tmpl.save(update_fields=['usage_count'])
        return JsonResponse({
            'type': 'task',
            'name': tmpl.name,
            'title': tmpl.title,
            'content': tmpl.content,
            'url': tmpl.url,
            'version': tmpl.version,
            'project': tmpl.project_id,
            'role': tmpl.role,
            'fallback': fallback,
            'hit': not fallback,
        })

    qs = qs_for(ReportTemplateVersion)
    primary = qs.filter(project__in=projects) if projects else qs
    tmpl = primary.order_by('-version', '-created_at').first()
    fallback = False
    if not tmpl and role:
        fallback_qs = qs.filter(project__isnull=True)
        tmpl = fallback_qs.order_by('-version', '-created_at').first()
        fallback = bool(tmpl)
    if not tmpl:
        return JsonResponse({'error': 'no report template'}, status=404)
    tmpl.usage_count = (tmpl.usage_count or 0) + 1
    tmpl.save(update_fields=['usage_count'])
    return JsonResponse({
        'type': 'report',
        'name': tmpl.name,
        'content': tmpl.content,
        'placeholders': tmpl.placeholders or {},
        'version': tmpl.version,
        'project': tmpl.project_id,
        'role': tmpl.role,
        'fallback': fallback,
        'hit': not fallback,
    })


@login_required
def template_recommend_api(request):
    """推荐模板：按 type + role + project 优先顺序返回，排序使用 usage_count 与最新更新时间。"""
    if request.method != 'GET':
        return _friendly_forbidden(request, "仅允许 GET / GET only")
    tpl_type = (request.GET.get('type') or 'report').strip()
    role = (request.GET.get('role') or '').strip() or None
    project_ids = request.GET.getlist('project') or [request.GET.get('project')]
    limit = int(request.GET.get('limit') or 8)
    limit = max(1, min(limit, 20))
    projects = []
    for pid in project_ids:
        if pid and str(pid).isdigit():
            proj = Project.objects.filter(id=int(pid)).first()
            if proj:
                projects.append(proj)

    def base_qs(model):
        q = Q(is_shared=True)
        if request.user.is_authenticated:
            q |= Q(created_by=request.user)
        qs = model.objects.filter(q)
        if role:
            qs = qs.filter(role=role)
        return qs

    if tpl_type == 'task':
        qs = base_qs(TaskTemplateVersion)
    else:
        qs = base_qs(ReportTemplateVersion)

    ordered = []
    if projects:
        ordered.extend(list(qs.filter(project__in=projects).order_by('-usage_count', '-created_at', '-version')[:limit]))
    ordered.extend(list(qs.filter(project__isnull=True).order_by('-usage_count', '-created_at', '-version')[:limit]))
    seen = set()
    recs = []
    for item in ordered:
        key = (item.name, item.project_id, item.role)
        if key in seen:
            continue
        seen.add(key)
        recs.append({
            'id': item.id,
            'name': item.name,
            'role': item.role,
            'project': item.project_id,
            'project_name': item.project.name if item.project else None,
            'usage_count': item.usage_count,
            'version': item.version,
        })
        if len(recs) >= limit:
            break
    return JsonResponse({'results': recs})

@login_required
def daily_report_create(request):
    user = request.user
    try:
        position = user.profile.position
    except Profile.DoesNotExist:
        position = 'dev'

    project_filter = Q(is_active=True)
    if not has_manage_permission(user):
        project_filter &= (Q(members=user) | Q(managers=user) | Q(owner=user))
    projects_qs = Project.objects.filter(project_filter).annotate(
        user_used=Count('reports', filter=Q(reports__user=user))
    ).distinct().order_by('-user_used', 'name')
    latest_report = DailyReport.objects.filter(user=user).order_by('-date', '-created_at').first()
    selected_project_ids = list(latest_report.projects.values_list('id', flat=True)) if latest_report else []
    role_value = position
    date_value = ''
    errors = []
    initial_values = {}

    existing_report = None
    # 防止重复日报：同一用户+日期+角色唯一

    if request.method == 'POST':
        date_str = request.POST.get('date')
        role = request.POST.get('role') or position
        role_value = role
        date_value = date_str
        project_ids = [int(pid) for pid in request.POST.getlist('projects') if pid.isdigit()]
        edit_report_id = request.POST.get('report_id')

        # 通用
        today_work = request.POST.get('today_work', '')
        progress_issues = request.POST.get('progress_issues', '')
        tomorrow_plan = request.POST.get('tomorrow_plan', '')

        # QA
        testing_scope = request.POST.get('testing_scope', '')
        testing_progress = request.POST.get('testing_progress', '')
        bug_summary = request.POST.get('bug_summary', '')
        testing_tomorrow = request.POST.get('testing_tomorrow', '')

        # 产品
        product_today = request.POST.get('product_today', '')
        product_coordination = request.POST.get('product_coordination', '')
        product_tomorrow = request.POST.get('product_tomorrow', '')

        # UI
        ui_today = request.POST.get('ui_today', '')
        ui_feedback = request.POST.get('ui_feedback', '')
        ui_tomorrow = request.POST.get('ui_tomorrow', '')

        # 运维
        ops_today = request.POST.get('ops_today', '')
        ops_monitoring = request.POST.get('ops_monitoring', '')
        ops_tomorrow = request.POST.get('ops_tomorrow', '')

        # 管理
        mgr_progress = request.POST.get('mgr_progress', '')
        mgr_risks = request.POST.get('mgr_risks', '')
        mgr_tomorrow = request.POST.get('mgr_tomorrow', '')

        if not role or role not in dict(DailyReport.ROLE_CHOICES):
            errors.append("请选择有效的角色")
        if date_str:
            parsed_date = parse_date(date_str)
            if not parsed_date:
                errors.append("日期格式不正确")
                parsed_date = None
        else:
            errors.append("请填写日期")
            parsed_date = None

        if not _has_role_content(role, {
            'today_work': today_work,
            'progress_issues': progress_issues,
            'tomorrow_plan': tomorrow_plan,
            'testing_scope': testing_scope,
            'testing_progress': testing_progress,
            'bug_summary': bug_summary,
            'testing_tomorrow': testing_tomorrow,
            'product_today': product_today,
            'product_coordination': product_coordination,
            'product_tomorrow': product_tomorrow,
            'ui_today': ui_today,
            'ui_feedback': ui_feedback,
            'ui_tomorrow': ui_tomorrow,
            'ops_today': ops_today,
            'ops_monitoring': ops_monitoring,
            'ops_tomorrow': ops_tomorrow,
            'mgr_progress': mgr_progress,
            'mgr_risks': mgr_risks,
            'mgr_tomorrow': mgr_tomorrow,
        }):
            errors.append("请填写与角色对应的内容，至少一项")

        if parsed_date and not edit_report_id:
        # 已存在同日期同角色时报错，引导去编辑
            existing_report = DailyReport.objects.filter(user=user, date=parsed_date, role=role).first()
            if existing_report:
                errors.append("该日期、该角色的日报已存在，请编辑已有日报。")

        if errors:
            context = {
                'user_position': position,
                'projects': projects_qs,
                'selected_project_ids': project_ids or selected_project_ids,
                'role_value': role_value,
                'date_value': date_value,
                'errors': errors,
                'form_user': user,
                'initial_values': {
                    'today_work': today_work,
                    'progress_issues': progress_issues,
                    'tomorrow_plan': tomorrow_plan,
                    'testing_scope': testing_scope,
                    'testing_progress': testing_progress,
                    'bug_summary': bug_summary,
                    'testing_tomorrow': testing_tomorrow,
                    'product_today': product_today,
                    'product_coordination': product_coordination,
                    'product_tomorrow': product_tomorrow,
                    'ui_today': ui_today,
                    'ui_feedback': ui_feedback,
                    'ui_tomorrow': ui_tomorrow,
                    'ops_today': ops_today,
                    'ops_monitoring': ops_monitoring,
                    'ops_tomorrow': ops_tomorrow,
                    'mgr_progress': mgr_progress,
                    'mgr_risks': mgr_risks,
                    'mgr_tomorrow': mgr_tomorrow,
                },
                'existing_report': existing_report,
            }
            return render(request, 'reports/daily_report_form.html', context)

        date = parsed_date or timezone.now().date()
        status = 'draft' if request.POST.get('submit_action') == 'draft' else 'submitted'

        if edit_report_id:
            report = get_object_or_404(DailyReport, pk=edit_report_id)
            if not (report.user == request.user or has_manage_permission(request.user)):
                return _friendly_forbidden(request, "无权限编辑该日报 / No permission to edit this report")
            conflict_exists = DailyReport.objects.filter(user=user, date=date, role=role).exclude(pk=report.pk).exists()
            # 编辑时避免与其他日报冲突
            if conflict_exists:
                errors.append("已存在相同日期与角色的日报，请调整日期或角色后再保存。")
                context = {
                    'user_position': position,
                    'projects': projects_qs,
                    'selected_project_ids': project_ids or selected_project_ids,
                    'role_value': role_value,
                    'date_value': date_value,
                    'errors': errors,
                    'initial_values': _report_initial(report),
                    'form_user': user,
                    'report_id': report.id,
                }
                return render(request, 'reports/daily_report_form.html', context)
            report.date = date
            report.role = role
            report.today_work = today_work
            report.progress_issues = progress_issues
            report.tomorrow_plan = tomorrow_plan
            report.testing_scope = testing_scope
            report.testing_progress = testing_progress
            report.bug_summary = bug_summary
            report.testing_tomorrow = testing_tomorrow
            report.product_today = product_today
            report.product_coordination = product_coordination
            report.product_tomorrow = product_tomorrow
            report.ui_today = ui_today
            report.ui_feedback = ui_feedback
            report.ui_tomorrow = ui_tomorrow
            report.ops_today = ops_today
            report.ops_monitoring = ops_monitoring
            report.ops_tomorrow = ops_tomorrow
            report.mgr_progress = mgr_progress
            report.mgr_risks = mgr_risks
            report.mgr_tomorrow = mgr_tomorrow
            report.status = status
            report.project = ''
            report.save()
        else:
            report, _ = DailyReport.objects.update_or_create(
                user=user,
                date=date,
                role=role,
                defaults={
                    'project': '',
                    'today_work': today_work,
                    'progress_issues': progress_issues,
                    'tomorrow_plan': tomorrow_plan,
                    'testing_scope': testing_scope,
                    'testing_progress': testing_progress,
                    'bug_summary': bug_summary,
                    'testing_tomorrow': testing_tomorrow,
                    'product_today': product_today,
                    'product_coordination': product_coordination,
                    'product_tomorrow': product_tomorrow,
                    'ui_today': ui_today,
                    'ui_feedback': ui_feedback,
                    'ui_tomorrow': ui_tomorrow,
                    'ops_today': ops_today,
                    'ops_monitoring': ops_monitoring,
                    'ops_tomorrow': ops_tomorrow,
                    'mgr_progress': mgr_progress,
                    'mgr_risks': mgr_risks,
                    'mgr_tomorrow': mgr_tomorrow,
                    'status': status,
                }
            )
        if project_ids:
            report.projects.set(project_ids)
        else:
            report.projects.clear()

        return redirect('reports:my_reports')

    context = {
        'user_position': position,
        'projects': projects_qs,
        'selected_project_ids': selected_project_ids,
        'role_value': role_value,
        'date_value': date_value,
        'errors': errors,
        'initial_values': initial_values,
        'form_user': user,
    }
    return render(request, 'reports/daily_report_form.html', context)


@login_required
def my_reports(request):
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    role = (request.GET.get('role') or '').strip()
    q = (request.GET.get('q') or '').strip()

    qs = DailyReport.objects.filter(user=request.user).select_related('user').prefetch_related('projects', 'user__profile').order_by('-date', '-created_at')
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    if status in dict(DailyReport.STATUS_CHOICES):
        qs = qs.filter(status=status)
    if project_id and project_id.isdigit():
        qs = qs.filter(projects__id=int(project_id))
    if role in dict(DailyReport.ROLE_CHOICES):
        qs = qs.filter(role=role)
    if q:
        qs = qs.filter(
            Q(today_work__icontains=q) |
            Q(progress_issues__icontains=q) |
            Q(tomorrow_plan__icontains=q) |
            Q(testing_scope__icontains=q) |
            Q(testing_progress__icontains=q) |
            Q(bug_summary__icontains=q) |
            Q(testing_tomorrow__icontains=q) |
            Q(product_today__icontains=q) |
            Q(product_coordination__icontains=q) |
            Q(product_tomorrow__icontains=q) |
            Q(ui_today__icontains=q) |
            Q(ui_feedback__icontains=q) |
            Q(ui_tomorrow__icontains=q) |
            Q(ops_today__icontains=q) |
            Q(ops_monitoring__icontains=q) |
            Q(ops_tomorrow__icontains=q) |
            Q(mgr_progress__icontains=q) |
            Q(mgr_risks__icontains=q) |
            Q(mgr_tomorrow__icontains=q)
        )

    paginator = Paginator(qs, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    today = timezone.localdate()
    has_today = qs.filter(date=today).exists()
    # streak: count consecutive days back from today with submitted
    dates = list(qs.filter(status='submitted').values_list('date', flat=True).order_by('-date'))
    streak = 0
    curr = today
    date_set = set(dates)
    while curr in date_set:
        streak += 1
        curr = curr - timedelta(days=1)

    context = {
        'reports': page_obj,
        'page_obj': page_obj,
        'start_date': start_date,
        'end_date': end_date,
        'status': status,
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'role': role,
        'q': q,
        'total_count': qs.count(),
        'latest_date': qs.first().date if qs.exists() else None,
        'projects': Project.objects.filter(
            Q(members=request.user) | Q(owner=request.user) | Q(managers=request.user) | Q(is_active=True)
        ).annotate(user_used=Count('reports', filter=Q(reports__user=request.user))).distinct().order_by('-user_used', 'name'),
        'has_today': has_today,
        'streak': streak,
    }
    return render(request, 'reports/my_reports.html', context)


@login_required
def my_reports_export(request):
    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    role = (request.GET.get('role') or '').strip()
    q = (request.GET.get('q') or '').strip()

    qs = DailyReport.objects.filter(user=request.user).select_related('user').prefetch_related('projects').order_by('-date', '-created_at')
    if start_date:
        qs = qs.filter(date__gte=start_date)
    if end_date:
        qs = qs.filter(date__lte=end_date)
    if status in dict(DailyReport.STATUS_CHOICES):
        qs = qs.filter(status=status)
    if project_id and project_id.isdigit():
        qs = qs.filter(projects__id=int(project_id))
    if role in dict(DailyReport.ROLE_CHOICES):
        qs = qs.filter(role=role)
    if q:
        qs = qs.filter(
            Q(today_work__icontains=q) |
            Q(progress_issues__icontains=q) |
            Q(tomorrow_plan__icontains=q) |
            Q(testing_scope__icontains=q) |
            Q(testing_progress__icontains=q) |
            Q(bug_summary__icontains=q) |
            Q(testing_tomorrow__icontains=q) |
            Q(product_today__icontains=q) |
            Q(product_coordination__icontains=q) |
            Q(product_tomorrow__icontains=q) |
            Q(ui_today__icontains=q) |
            Q(ui_feedback__icontains=q) |
            Q(ui_tomorrow__icontains=q) |
            Q(ops_today__icontains=q) |
            Q(ops_monitoring__icontains=q) |
            Q(ops_tomorrow__icontains=q) |
            Q(mgr_progress__icontains=q) |
            Q(mgr_risks__icontains=q) |
            Q(mgr_tomorrow__icontains=q)
        )
    if qs.count() > MAX_EXPORT_ROWS:
        return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters.", status=400)

    rows = (
        [
            r.date.isoformat(),
            r.get_role_display(),
            r.get_status_display(),
            r.project_names,
            (r.summary or '')[:200].replace('\n', ' '),
            timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
        ]
        for r in qs.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["日期", "角色", "状态", "项目", "摘要", "创建时间"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="my_reports.csv"'
    log_action(request, 'export', f"my_reports count={qs.count()} q={q}")
    return response


def register(request):
    if request.user.is_authenticated:
        return redirect('reports:daily_report_create')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('reports:daily_report_create')
    else:
        form = RegistrationForm()

    return render(request, 'registration/register.html', {
        'form': form,
        'password_min_score': getattr(settings, 'PASSWORD_MIN_SCORE', 3),
    })


def logout_view(request):
    """
    Allow GET/POST logout and show a friendly logged-out page.
    """
    logout(request)
    return render(request, 'registration/logged_out.html')


@login_required
def send_email_code_api(request):
    """API for sending email verification code."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        email = data.get('email', '').strip()
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not email:
        return JsonResponse({'error': '请输入邮箱地址 / Please enter email address'}, status=400)

    # Check if email is valid format (simple check)
    if '@' not in email or '.' not in email:
        return JsonResponse({'error': '邮箱格式不正确 / Invalid email format'}, status=400)

    user = request.user
    UserModel = get_user_model()
    
    # Check availability
    if UserModel.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        return JsonResponse({'error': '该邮箱已被其他账号使用 / Email already in use'}, status=400)
    
    if email.lower() == (user.email or '').lower():
         return JsonResponse({'error': '该邮箱已绑定，无需重复验证 / Email already bound'}, status=400)

    # Cooldown check
    cooldown = 60
    now_ts = time.time()
    last_send = request.session.get('email_verification_last_send') or 0
    if now_ts - last_send < cooldown:
        remain = int(cooldown - (now_ts - last_send))
        return JsonResponse({'error': f'发送过于频繁，请 {remain} 秒后再试 / Too frequent, try again in {remain}s'}, status=429)

    code = f"{random.randint(100000, 999999)}"
    subject = "邮箱验证 / Email verification code"
    body = (
        f"您的验证码(your code)：{code}\n"
        f"10 分钟内有效，请勿泄露。If you did not request this, please ignore."
    )
    
    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL or settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception as exc:
        log_action(request, 'error', f"send email code failed to {email}", data={'error': str(exc)})
        return JsonResponse({'error': '验证码发送失败，请联系管理员 / Failed to send email'}, status=500)

    # Save to session
    request.session['email_verification'] = {
        'email': email,
        'code': code,
        'expires_at': time.time() + 600,
    }
    request.session['email_verification_last_send'] = now_ts
    request.session.modified = True
    
    log_action(request, 'update', f"send email code to {email}")
    
    msg = f"验证码已发送至 {email}"
    if settings.DEBUG:
        msg += f" (Code: {code})"
        
    return JsonResponse({'success': True, 'message': msg})


@login_required
def account_settings(request):
    """个人中心：用户名、密码与邮箱设置。"""
    user = request.user
    UserModel = get_user_model()
    username_form = UsernameUpdateForm(user=user, initial={'username': user.username})
    password_form = PasswordUpdateForm(user=user)
    email_request_form = EmailVerificationRequestForm(initial={'email': user.email})
    email_confirm_form = EmailVerificationConfirmForm(initial={'email': user.email})

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'change_username':
            username_form = UsernameUpdateForm(user=user, data=request.POST)
            if username_form.is_valid():
                old_username = user.username
                new_username = username_form.cleaned_data['username']
                user.username = new_username
                user.save(update_fields=['username'])
                messages.success(request, "用户名已更新 / Username updated successfully")
                log_action(request, 'update', f"username {old_username} -> {new_username}")
                return redirect('account_settings')
            
        elif action == 'change_password':
            password_form = PasswordUpdateForm(user=user, data=request.POST)
            if password_form.is_valid():
                new_password = password_form.cleaned_data['new_password1']
                user.set_password(new_password)
                user.save()
                update_session_auth_hash(request, user)  # Keep user logged in
                log_action(request, 'update', "password changed")
                messages.success(request, "密码已更新 / Password updated successfully")
                return redirect('account_settings')

        elif action == 'update_email':
            email_confirm_form = EmailVerificationConfirmForm(data=request.POST)
            if email_confirm_form.is_valid():
                email = email_confirm_form.cleaned_data['email']
                code = email_confirm_form.cleaned_data['code']
                pending = request.session.get('email_verification') or {}
                
                if not pending or pending.get('email') != email:
                    messages.error(request, "请先获取该邮箱的验证码 / Please request code first")
                elif pending.get('expires_at', 0) < time.time():
                    messages.error(request, "验证码已过期 / Code expired")
                elif str(pending.get('code')) != str(code):
                    messages.error(request, "验证码不正确 / Invalid code")
                elif UserModel.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
                    messages.error(request, "邮箱已被其他账号使用 / Email already in use")
                else:
                    user.email = email
                    user.save(update_fields=['email'])
                    request.session.pop('email_verification', None)
                    request.session.modified = True
                    
                    if hasattr(user, 'profile'):
                        user.profile.email_verified = True
                        user.profile.save()

                    messages.success(request, "邮箱已更新并完成验证 / Email updated and verified")
                    log_action(request, 'update', f"email updated to {email}")
                    return redirect('account_settings')
            else:
                messages.error(request, "输入有误，请检查 / Invalid input")

    # Calculate user statistics
    from django.utils import timezone
    from datetime import timedelta
    
    today = timezone.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    
    user_reports = DailyReport.objects.filter(user=user)
    week_reports = user_reports.filter(date__gte=week_start)
    month_reports = user_reports.filter(date__gte=month_start)
    
    # Statistics
    week_report_count = week_reports.count()
    month_report_count = month_reports.count()
    total_report_count = user_reports.count()
    
    # Calculate completion rate (reports submitted vs expected)
    expected_week_reports = 7  # Assuming 7 days a week
    completion_rate = min(100, int((week_report_count / expected_week_reports) * 100)) if expected_week_reports > 0 else 0
    
    # Project participation
    if hasattr(user, 'profile'):
        project_count = user.profile.projects.count()
    else:
        project_count = 0
    
    # Average completion time (placeholder - would need timestamp data)
    avg_completion_time = 2.5  # hours (placeholder)
    
    pending_email = request.session.get('email_verification')
    context = {
        'username_form': username_form,
        'password_form': password_form,
        'email_request_form': email_request_form,
        'email_confirm_form': email_confirm_form,
        'pending_email': pending_email,
        'password_min_score': getattr(settings, 'PASSWORD_MIN_SCORE', 3),
        # Statistics data
        'week_report_count': week_report_count,
        'month_report_count': month_report_count,
        'total_report_count': total_report_count,
        'completion_rate': completion_rate,
        'project_count': project_count,
        'avg_completion_time': avg_completion_time,
    }
    return render(request, 'registration/account_settings.html', context)


@login_required
def report_detail(request, pk: int):
    qs = DailyReport.objects.select_related('user').prefetch_related('projects')
    if has_manage_permission(request.user):
        report = get_object_or_404(qs, pk=pk)
    else:
        report = get_object_or_404(qs, pk=pk)
        can_manage_project = report.projects.filter(managers=request.user).exists()
        if not (report.user == request.user or can_manage_project):
            return _friendly_forbidden(request, "无权限查看该日报 / No permission to view this report")

    sections = _build_sections(report)

    context = {
        'report': report,
        'sections': sections,
        'can_submit': report.status == 'draft' and (report.user == request.user or has_manage_permission(request.user)),
    }
    return render(request, 'reports/report_detail.html', context)


@login_required
def report_submit(request, pk: int):
    report = get_object_or_404(DailyReport, pk=pk)
    if not (report.user == request.user or has_manage_permission(request.user)):
        return _friendly_forbidden(request, "无权限提交该日报 / No permission to submit this report")
    report.status = 'submitted'
    report.save(update_fields=['status', 'updated_at'])
    return redirect('reports:report_detail', pk=pk)


@login_required
def report_edit(request, pk: int):
    report = get_object_or_404(DailyReport.objects.select_related('user').prefetch_related('projects'), pk=pk)
    if not (report.user == request.user or has_manage_permission(request.user)):
        return _friendly_forbidden(request, "无权限编辑该日报 / No permission to edit this report")

    position = getattr(getattr(report.user, 'profile', None), 'position', 'dev')
    project_filter = Q(is_active=True)
    if not has_manage_permission(request.user):
        project_filter &= (Q(owner=request.user) | Q(members=request.user) | Q(managers=request.user))
    projects_qs = Project.objects.filter(project_filter).distinct().order_by('name')
    selected_project_ids = list(report.projects.values_list('id', flat=True))
    errors = []

    if request.method == 'POST':
        return daily_report_create(request)  # reuse logic by same endpoint?  # noqa

    context = {
        'user_position': position,
        'projects': projects_qs,
        'selected_project_ids': selected_project_ids,
        'role_value': report.role,
        'date_value': report.date,
        'errors': errors,
        'initial_values': _report_initial(report),
        'editing': True,
        'report_id': report.id,
        'form_user': report.user,
    }
    return render(request, 'reports/daily_report_form.html', context)


@login_required
def admin_reports(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    reports, role, start_date, end_date = _filtered_reports(request)
    username = (request.GET.get('username') or '').strip()
    user_id = request.GET.get('user')
    project_id = request.GET.get('project')
    status = (request.GET.get('status') or '').strip()

    if username:
        reports = reports.filter(
            Q(user__username__icontains=username) |
            Q(user__first_name__icontains=username) |
            Q(user__last_name__icontains=username)
        )
    if project_id and project_id.isdigit():
        reports = reports.filter(projects__id=int(project_id))
    if user_id and user_id.isdigit():
        reports = reports.filter(user_id=int(user_id))
    if status in dict(DailyReport.STATUS_CHOICES):
        reports = reports.filter(status=status)

    total_count = reports.count()
    paginator = Paginator(reports, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    log_action(request, 'access', f"admin_reports count={total_count} role={role} start={start_date} end={end_date} username={username} project={project_id} status={status}")
    context = {
        'reports': page_obj,
        'page_obj': page_obj,
        'total_count': total_count,
        'report_role_choices': DailyReport.ROLE_CHOICES,
        'role': role,
        'start_date': start_date,
        'end_date': end_date,
        'username': username,
        'user_id': int(user_id) if user_id and user_id.isdigit() else '',
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'projects': Project.objects.filter(is_active=True).order_by('name'),
        'users': get_user_model().objects.order_by('username'),
        'status': status,
    }
    return render(request, 'reports/admin_reports.html', context)


@login_required
def task_list(request):
    """User-facing task list with filters and completion button."""
    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'

    # 优化查询，使用select_related和prefetch_related减少数据库查询
    tasks_qs = Task.objects.select_related(
        'project', 'user', 'user__profile', 'sla_timer'
    ).prefetch_related(
        'comments', 'attachments'
    ).filter(user=request.user).order_by('-created_at')
    
    now = timezone.now()
    
    project_obj = None
    if project_id and project_id.isdigit():
        project_obj = Project.objects.filter(id=int(project_id)).first()
    
    # 预取SLA设置，避免在循环中重复查询
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
    
    sla_hours = get_sla_hours(project_obj, system_setting_value=sla_hours_val)
    
    due_soon_ids = set(tasks_qs.filter(
        status__in=['pending', 'in_progress', 'on_hold', 'reopened'],
        due_at__gt=now,
        due_at__lte=now + timedelta(hours=sla_hours)
    ).values_list('id', flat=True))

    # 应用过滤器
    if status:
        tasks_qs = tasks_qs.filter(status=status)
    if project_id and project_id.isdigit():
        tasks_qs = tasks_qs.filter(project_id=project_id)
    if q:
        tasks_qs = tasks_qs.filter(title__icontains=q)

    if hot:  # 显示即将到期的任务
        tasks_qs = tasks_qs.filter(id__in=due_soon_ids)

    # 分页
    paginator = Paginator(tasks_qs, 20)
    page_number = request.GET.get('page')
    tasks = paginator.get_page(page_number)

    # 批量计算SLA信息，避免在模板中逐个计算
    for task in tasks:
        task.sla_info = calculate_sla_info(task, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)

    # 获取项目列表用于筛选
    projects = Project.objects.filter(
        id__in=Task.objects.filter(user=request.user).values_list('project_id', flat=True)
    )

    return render(request, 'reports/task_list.html', {
        'tasks': tasks,
        'projects': projects,
        'selected_status': status,
        'selected_project_id': int(project_id) if project_id and project_id.isdigit() else None,
        'q': q,
        'hot': hot,
        'due_soon_count': len(due_soon_ids),
    })


@login_required
def task_export(request):
    """导出当前筛选的我的任务列表。"""
    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'

    tasks = Task.objects.select_related('project', 'user', 'user__profile', 'sla_timer').filter(user=request.user).order_by('-created_at')
    
    if status in dict(Task.STATUS_CHOICES):
        tasks = tasks.filter(status=status)
    if project_id and project_id.isdigit():
        tasks = tasks.filter(project_id=int(project_id))
    if q:
        tasks = tasks.filter(Q(title__icontains=q) | Q(content__icontains=q))
    if hot:
        filtered = []
        # Pre-fetch SLA settings once
        cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
        sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
        cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
        sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None

        for t in tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE):
            info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
            if info['status'] in ('tight', 'overdue'):
                t.sla_info = info
                filtered.append(t)
        tasks = filtered
    total_count = tasks.count() if hasattr(tasks, 'count') else len(tasks)
    if total_count > MAX_EXPORT_ROWS:
        if request.GET.get('queue') != '1':
            return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters. 如需排队导出，请带 queue=1 参数 / Use queue=1 to enqueue export.", status=400)
        # 走异步导出队列（简化为后台生成 + 轮询）
        job = _create_export_job(request.user, 'my_tasks')
        try:
            path = _generate_export_file(
                job,
                ["标题", "项目", "状态", "截止", "完成时间", "URL"],
                (
                    [
                        t.title,
                        t.project.name,
                        t.get_status_display(),
                        t.due_at.isoformat() if t.due_at else '',
                        t.completed_at.isoformat() if t.completed_at else '',
                        t.url or '',
                    ]
                    for t in (tasks if isinstance(tasks, list) else tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE))
                )
            )
            return JsonResponse({'queued': True, 'job_id': job.id})
        except Exception as e:
            job.status = 'failed'
            job.message = str(e)
            job.save(update_fields=['status', 'message', 'updated_at'])
            return JsonResponse({'error': 'export failed'}, status=500)

    rows = (
        [
            t.title,
            t.project.name,
            t.get_status_display(),
            t.due_at.isoformat() if t.due_at else '',
            t.completed_at.isoformat() if t.completed_at else '',
            t.url or '',
        ]
        for t in (tasks if isinstance(tasks, list) else tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE))
    )
    header = ["标题", "项目", "状态", "截止", "完成时间", "URL"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename=\"tasks.csv\"'
    log_action(request, 'export', f"tasks count={total_count} q={q}")
    return response


@login_required
def task_export_selected(request):
    """导出选中的任务（我的任务）。"""
    if request.method != 'POST':
        return _admin_forbidden(request, "仅允许 POST / POST only")
    ids = request.POST.getlist('task_ids')
    tasks = Task.objects.select_related('project').filter(user=request.user, id__in=ids)
    _mark_overdue_tasks(tasks)
    if not tasks.exists():
        return HttpResponse("请选择任务后导出", status=400)
    rows = (
        [
            t.title,
            t.project.name,
            t.get_status_display(),
            t.due_at.isoformat() if t.due_at else '',
            t.completed_at.isoformat() if t.completed_at else '',
            t.url or '',
        ]
        for t in tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["标题", "项目", "状态", "截止", "完成时间", "URL"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename=\"tasks_selected.csv\"'
    log_action(request, 'export', f"tasks_selected count={tasks.count()}")
    return response


@login_required
def export_job_status(request, job_id: int):
    job = get_object_or_404(ExportJob, id=job_id, user=request.user)
    if job.expires_at and job.expires_at < timezone.now():
        job.status = 'failed'
        job.message = '导出已过期 / Export expired'
        job.save(update_fields=['status', 'message', 'updated_at'])
        if job.file_path and os.path.exists(job.file_path):
            try:
                os.remove(job.file_path)
            except OSError:
                pass
    data = {
        'job_id': job.id,
        'status': job.status,
        'progress': job.progress,
        'message': job.message,
        'download_url': reverse('reports:export_job_download', args=[job.id]) if job.status == 'done' else '',
    }
    return JsonResponse(data)


@login_required
def export_job_download(request, job_id: int):
    job = get_object_or_404(ExportJob, id=job_id, user=request.user, status='done')
    if job.expires_at and job.expires_at < timezone.now():
        return _friendly_forbidden(request, "文件已过期，请重新导出 / File expired, please export again")
    if not job.file_path or not os.path.exists(job.file_path):
        return _friendly_forbidden(request, "文件不存在 / File missing")
    filename = f"{job.export_type}.csv"
    def file_iter(path):
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    yield chunk
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    response = StreamingHttpResponse(file_iter(job.file_path), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def task_complete(request, pk: int):
    task = get_object_or_404(Task, pk=pk, user=request.user)
    if request.method != 'POST':
        return _friendly_forbidden(request, "仅允许 POST / POST only")
    # 完成任务
    try:
        with transaction.atomic():
            _add_history(task, request.user, 'status', task.status, 'completed')
            task.status = 'completed'
            task.completed_at = timezone.now()
            timer = _get_sla_timer_readonly(task)
            if timer and timer.paused_at:
                timer.total_paused_seconds += int((timezone.now() - timer.paused_at).total_seconds())
                timer.paused_at = None
                timer.save(update_fields=['total_paused_seconds', 'paused_at'])
            task.save(update_fields=['status', 'completed_at'])
        log_action(request, 'update', f"task_complete {task.id}")
        messages.success(request, "任务已标记完成 / Task marked as completed.")
    except Exception as exc:
        messages.error(request, f"任务完成失败，请重试 / Failed to complete task: {exc}")
    return redirect('reports:task_list')


@login_required
def task_bulk_action(request):
    if request.method != 'POST':
        return _admin_forbidden(request, "仅允许 POST / POST only")
    ids = request.POST.getlist('task_ids')
    action = request.POST.get('bulk_action')
    redirect_to = request.POST.get('redirect_to') or None
    tasks = Task.objects.filter(user=request.user, id__in=ids)
    skipped_perm = max(0, len(ids) - tasks.count())
    total_selected = tasks.count()
    updated = 0
    if action == 'complete':
        now = timezone.now()
        for t in tasks:
            _add_history(t, request.user, 'status', t.status, 'completed')
        tasks.update(status='completed', completed_at=now)
        updated = total_selected
        log_action(request, 'update', f"task_bulk_complete count={tasks.count()}")
    elif action == 'reopen':
        for t in tasks:
            _add_history(t, request.user, 'status', t.status, 'reopened')
        tasks.update(status='reopened', completed_at=None)
        updated = total_selected
        log_action(request, 'update', f"task_bulk_reopen count={tasks.count()}")
    elif action == 'update':
        status_value = (request.POST.get('status_value') or '').strip()
        due_at_str = (request.POST.get('due_at') or '').strip()
        parsed_due = None
        if due_at_str:
            try:
                parsed = datetime.fromisoformat(due_at_str)
                parsed_due = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except ValueError:
                messages.error(request, "截止时间格式不正确 / Invalid due date format")
                return redirect(redirect_to or 'reports:task_list')
        valid_status = status_value in dict(Task.STATUS_CHOICES)
        updated = 0
        now = timezone.now()
        for t in tasks:
            update_fields = []
            if valid_status and status_value != t.status:
                _add_history(t, request.user, 'status', t.status, status_value)
                t.status = status_value
                if status_value == 'completed':
                    t.completed_at = now
                    update_fields.append('completed_at')
                else:
                    if t.completed_at:
                        t.completed_at = None
                        update_fields.append('completed_at')
                update_fields.append('status')
            if parsed_due and (t.due_at != parsed_due):
                _add_history(t, request.user, 'due_at', t.due_at.isoformat() if t.due_at else '', parsed_due.isoformat())
                t.due_at = parsed_due
                update_fields.append('due_at')
            if update_fields:
                t.save(update_fields=update_fields)
                updated += 1
        if updated:
            log_action(request, 'update', f"task_bulk_update status={status_value or '-'} due_at={'yes' if parsed_due else 'no'} count={updated}")
    if skipped_perm:
        messages.warning(request, f"{skipped_perm} 条因无权限未处理")
    if updated:
        messages.success(request, f"批量操作完成：更新 {updated}/{total_selected} 条")
    else:
        messages.info(request, "未更新任何任务，请检查操作与选择")
    log_action(
        request,
        'update',
        f"task_bulk_action {action or '-'} updated={updated} total={total_selected} skipped_perm={skipped_perm}",
        data={'action': action, 'updated': updated, 'total': total_selected, 'skipped_perm': skipped_perm},
    )
    _invalidate_stats_cache()
    return redirect(redirect_to or 'reports:task_list')


@login_required
def task_view(request, pk: int):
    """View task content or redirect to URL."""
    if has_manage_permission(request.user):
        task = get_object_or_404(Task.objects.select_related('project', 'user'), pk=pk)
    else:
        task = get_object_or_404(Task.objects.select_related('project', 'user'), pk=pk, user=request.user)

    # 到期未完成自动标记逾期
    if task.due_at and task.status in ('pending', 'reopened') and task.due_at < timezone.now():
        task.status = 'overdue'
        task.save(update_fields=['status'])

    if request.method == 'POST' and 'action' in request.POST:
        if request.POST.get('action') == 'add_comment':
            comment_text = (request.POST.get('comment') or '').strip()
            if comment_text:
                # 记录任务评论，便于协作
                mentions = []
                usernames = set(MENTION_PATTERN.findall(comment_text))
                if usernames:
                    User = get_user_model()
                    mention_users = list(User.objects.filter(username__in=usernames))
                    mentions = [u.username for u in mention_users]
                    if mention_users:
                        _notify(request, mention_users, f"任务 {task.id} 评论提及")
                TaskComment.objects.create(task=task, user=request.user, content=comment_text, mentions=mentions)
                log_action(request, 'create', f"task_comment {task.id}")
        elif request.POST.get('action') == 'reopen' and task.status == 'completed':
            # 已完成任务支持重新打开
            _add_history(task, request.user, 'status', task.status, 'reopened')
            task.status = 'reopened'
            task.completed_at = None
            task.save(update_fields=['status', 'completed_at'])
            log_action(request, 'update', f"task_reopen {task.id}")
        elif request.POST.get('action') == 'pause_timer':
            timer = _ensure_sla_timer(task)
            if not timer.paused_at:
                timer.paused_at = timezone.now()
                timer.save(update_fields=['paused_at'])
                if task.status != 'on_hold':
                    _add_history(task, request.user, 'status', task.status, 'on_hold')
                    task.status = 'on_hold'
                    task.save(update_fields=['status'])
                messages.success(request, "计时已暂停")
                log_action(request, 'update', f"task_pause {task.id}")
        elif request.POST.get('action') == 'resume_timer':
            timer = _ensure_sla_timer(task)
            if timer.paused_at:
                timer.total_paused_seconds += int((timezone.now() - timer.paused_at).total_seconds())
                timer.paused_at = None
                timer.save(update_fields=['total_paused_seconds', 'paused_at'])
                if task.status == 'on_hold':
                    _add_history(task, request.user, 'status', task.status, 'in_progress')
                    task.status = 'in_progress'
                    task.save(update_fields=['status'])
                messages.success(request, "计时已恢复")
                log_action(request, 'update', f"task_resume {task.id}")
        elif request.POST.get('action') == 'add_attachment':
            attach_url = (request.POST.get('attachment_url') or '').strip()
            attach_file = request.FILES.get('attachment_file')
            if attach_file:
                max_size = 2 * 1024 * 1024
                if attach_file.size > max_size:
                    messages.error(request, "附件大小超出 2MB 限制")
                    log_action(request, 'update', f"task_attachment_reject_size {task.id}")
                else:
                    allowed_types = ['application/pdf', 'image/png', 'image/jpeg', 'text/plain']
                    allowed_ext = ('.pdf', '.png', '.jpg', '.jpeg', '.txt')
                    if attach_file.content_type not in allowed_types or not attach_file.name.lower().endswith(allowed_ext):
                        messages.error(request, "附件类型仅支持 pdf/png/jpg/txt")
                        log_action(request, 'update', f"task_attachment_reject_type {task.id}")
                    else:
                        TaskAttachment.objects.create(task=task, user=request.user, url=attach_url, file=attach_file)
                        messages.success(request, "附件已上传")
                        log_action(request, 'create', f"task_attachment {task.id}")
            elif attach_url:
                TaskAttachment.objects.create(task=task, user=request.user, url=attach_url, file=attach_file)
                messages.success(request, "附件链接已添加")
                log_action(request, 'create', f"task_attachment {task.id}")
        elif request.POST.get('action') == 'set_status':
            new_status = request.POST.get('status_value')
            if new_status in dict(Task.STATUS_CHOICES):
                try:
                    with transaction.atomic():
                        _add_history(task, request.user, 'status', task.status, new_status)
                        if new_status == 'completed':
                            task.status = 'completed'
                            task.completed_at = timezone.now()
                            timer = _get_sla_timer_readonly(task)
                            if timer and timer.paused_at:
                                timer.total_paused_seconds += int((timezone.now() - timer.paused_at).total_seconds())
                                timer.paused_at = None
                                timer.save(update_fields=['total_paused_seconds', 'paused_at'])
                        else:
                            task.status = new_status
                            if task.completed_at:
                                task.completed_at = None
                        task.save(update_fields=['status', 'completed_at'])
                    log_action(request, 'update', f"task_status {task.id} -> {new_status}")
                    messages.success(request, "状态已更新 / Status updated.")
                except Exception as exc:
                    messages.error(request, f"状态更新失败，请重试 / Failed to update status: {exc}")
        return redirect('reports:task_view', pk=pk)

    log_action(request, 'access', f"task_view {task.id}")
    comments = task.comments.select_related('user').all()
    attachments = task.attachments.select_related('user').all()
    histories = task.histories.select_related('user').all()
    sla_ref_time = task.completed_at if task.completed_at else None
    return render(request, 'reports/task_detail.html', {
        'task': task,
        'comments': comments,
        'attachments': attachments,
        'histories': histories,
        'sla': calculate_sla_info(task, as_of=sla_ref_time),
    })


@login_required
def admin_task_list(request):
    manageable_project_ids = set(Project.objects.filter(managers=request.user, is_active=True).values_list('id', flat=True))
    is_admin = has_manage_permission(request.user)
    if not is_admin and not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")

    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'

    tasks_qs = Task.objects.select_related('project', 'user', 'user__profile').order_by('-created_at')
    
    # Pre-fetch SLA settings once
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
    
    now = timezone.now()
    # Default SLA hours for general query if no project specific
    default_sla_hours = get_sla_hours(system_setting_value=sla_hours_val)
    
    due_soon_ids = set(tasks_qs.filter(
        status__in=['pending', 'in_progress', 'on_hold', 'reopened'],
        due_at__gt=now,
        due_at__lte=now + timedelta(hours=default_sla_hours)
    ).values_list('id', flat=True))
    
    if not is_admin:
        tasks_qs = tasks_qs.filter(project_id__in=manageable_project_ids)
    if status in dict(Task.STATUS_CHOICES):
        tasks_qs = tasks_qs.filter(status=status)
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if is_admin or pid in manageable_project_ids:
            tasks_qs = tasks_qs.filter(project_id=pid)
        else:
            tasks_qs = tasks_qs.none()
    if user_id and user_id.isdigit():
        tasks_qs = tasks_qs.filter(user_id=int(user_id))
    if q:
        tasks_qs = tasks_qs.filter(Q(title__icontains=q) | Q(content__icontains=q))

    if hot:
        tasks = list(tasks_qs)
        tasks = [t for t in tasks if calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)['status'] in ('tight', 'overdue')]
        
        far_future = now + timedelta(days=365)
        for t in tasks:
            t.is_due_soon = t.id in due_soon_ids
            t.sla_info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
        tasks.sort(key=lambda t: (
            -t.created_at.timestamp(),
            t.sla_info.get('sort', 3),
            t.sla_info.get('remaining_hours') if t.sla_info.get('remaining_hours') is not None else 9999,
            t.due_at or far_future,
        ))
        paginator = Paginator(tasks, 15)
        page_obj = paginator.get_page(request.GET.get('page'))
    else:
        # DB Pagination for standard view (Performance Optimization)
        paginator = Paginator(tasks_qs, 15)
        page_obj = paginator.get_page(request.GET.get('page'))
        for t in page_obj:
            t.is_due_soon = t.id in due_soon_ids
            t.sla_info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)

    User = get_user_model()
    if is_admin:
        user_objs = User.objects.all().order_by('username')
        project_choices = Project.objects.filter(is_active=True).order_by('name')
    else:
        project_choices = Project.objects.filter(id__in=manageable_project_ids).order_by('name')
        user_objs = User.objects.filter(
            Q(project_memberships__id__in=manageable_project_ids) |
            Q(managed_projects__id__in=manageable_project_ids) |
            Q(owned_projects__id__in=manageable_project_ids)
        ).distinct().order_by('username')
    return render(request, 'reports/admin_task_list.html', {
        'tasks': page_obj,
        'page_obj': page_obj,
        'status': status,
        'q': q,
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'user_id': int(user_id) if user_id and user_id.isdigit() else '',
        'hot': hot,
        'projects': project_choices,
        'users': user_objs,
        'task_status_choices': Task.STATUS_CHOICES,
        'due_soon_ids': due_soon_ids,
        'sla_config_hours': default_sla_hours,
        'redirect_to': request.get_full_path(),
        'sla_thresholds': get_sla_thresholds(system_setting_value=sla_thresholds_val),
    })


@login_required
def admin_task_bulk_action(request):
    manageable_project_ids = set(Project.objects.filter(managers=request.user, is_active=True).values_list('id', flat=True))
    is_admin = has_manage_permission(request.user)
    if not is_admin and not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")
    if request.method != 'POST':
        return _admin_forbidden(request, "仅允许 POST / POST only")
    ids = request.POST.getlist('task_ids')
    action = request.POST.get('bulk_action')
    redirect_to = request.POST.get('redirect_to') or None
    total_requested = len(ids)
    tasks = Task.objects.filter(id__in=ids)
    if not is_admin:
        tasks = tasks.filter(project_id__in=manageable_project_ids)
    skipped_perm = max(0, total_requested - tasks.count())
    total_selected = tasks.count()
    updated = 0
    if action == 'complete':
        now = timezone.now()
        for t in tasks:
            _add_history(t, request.user, 'status', t.status, 'completed')
        tasks.update(status='completed', completed_at=now)
        updated = total_selected
        log_action(request, 'update', f"admin_task_bulk_complete count={tasks.count()}")
    elif action == 'reopen':
        for t in tasks:
            _add_history(t, request.user, 'status', t.status, 'reopened')
        tasks.update(status='reopened', completed_at=None)
        updated = total_selected
        log_action(request, 'update', f"admin_task_bulk_reopen count={tasks.count()}")
    elif action == 'overdue':
        for t in tasks:
            _add_history(t, request.user, 'status', t.status, 'overdue')
        tasks.update(status='overdue')
        updated = total_selected
        log_action(request, 'update', f"admin_task_bulk_overdue count={tasks.count()}")
    elif action == 'update':
        status_value = (request.POST.get('status_value') or '').strip()
        due_at_str = (request.POST.get('due_at') or '').strip()
        assign_to = request.POST.get('assign_to')
        parsed_due = None
        if due_at_str:
            try:
                parsed = datetime.fromisoformat(due_at_str)
                parsed_due = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except ValueError:
                messages.error(request, "截止时间格式不正确 / Invalid due date format")
                return redirect(redirect_to or 'reports:admin_task_list')
        valid_status = status_value in dict(Task.STATUS_CHOICES)
        assign_user = None
        if assign_to and assign_to.isdigit():
            assign_user = get_user_model().objects.filter(id=int(assign_to)).first()
        updated = 0
        now = timezone.now()
        for t in tasks:
            update_fields = []
            if valid_status and status_value != t.status:
                _add_history(t, request.user, 'status', t.status, status_value)
                t.status = status_value
                if status_value == 'completed':
                    t.completed_at = now
                    update_fields.append('completed_at')
                else:
                    if t.completed_at:
                        t.completed_at = None
                        update_fields.append('completed_at')
                update_fields.append('status')
            if parsed_due and (t.due_at != parsed_due):
                _add_history(t, request.user, 'due_at', t.due_at.isoformat() if t.due_at else '', parsed_due.isoformat())
                t.due_at = parsed_due
                update_fields.append('due_at')
            if assign_user and assign_user.id != t.user_id and (is_admin or t.project_id in manageable_project_ids):
                _add_history(t, request.user, 'user', t.user.username if t.user else '', assign_user.username)
                t.user = assign_user
                update_fields.append('user')
            if update_fields:
                t.save(update_fields=update_fields)
                updated += 1
        if updated:
            log_action(request, 'update', f"admin_task_bulk_update status={status_value or '-'} due_at={'yes' if parsed_due else 'no'} assign={'yes' if assign_user else 'no'} count={updated}")
    if updated:
        messages.success(request, f"批量操作完成：更新 {updated}/{total_selected} 条")
        if skipped_perm:
            messages.warning(request, f"{skipped_perm} 条因无权限未处理")
        elif total_selected and updated < total_selected:
            messages.warning(request, f"{total_selected - updated} 条未更新，可能因缺少字段或权限限制")
    else:
        messages.info(request, "未更新任何任务，请检查操作与选择")
    log_action(
        request,
        'update',
        f"admin_task_bulk_action {action or '-'} updated={updated} total={total_selected} skipped_perm={skipped_perm}",
        data={
            'action': action,
            'updated': updated,
            'total': total_selected,
            'skipped_perm': skipped_perm,
            'project_filter': project_id,
            'user_filter': user_id,
        },
    )
    _invalidate_stats_cache()
    return redirect(redirect_to or 'reports:admin_task_list')


@login_required
def admin_task_export(request):
    manageable_project_ids = set(Project.objects.filter(managers=request.user, is_active=True).values_list('id', flat=True))
    is_admin = has_manage_permission(request.user)
    if not is_admin and not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")

    status = (request.GET.get('status') or '').strip()
    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    q = (request.GET.get('q') or '').strip()
    hot = request.GET.get('hot') == '1'

    tasks = Task.objects.select_related('project', 'user').order_by('-created_at')
    
    # Pre-fetch SLA settings once
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
    
    if not is_admin:
        tasks = tasks.filter(project_id__in=manageable_project_ids)
    if status in dict(Task.STATUS_CHOICES):
        tasks = tasks.filter(status=status)
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if is_admin or pid in manageable_project_ids:
            tasks = tasks.filter(project_id=pid)
        else:
            tasks = tasks.none()
    if user_id and user_id.isdigit():
        tasks = tasks.filter(user_id=int(user_id))
    if q:
        tasks = tasks.filter(Q(title__icontains=q) | Q(content__icontains=q))
    if hot:
        filtered = []
        for t in tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE):
            info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
            if info['status'] in ('tight', 'overdue'):
                t.sla_info = info
                filtered.append(t)
        tasks = filtered

    total_count = tasks.count() if hasattr(tasks, 'count') else len(tasks)
    if total_count > MAX_EXPORT_ROWS:
        return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters.", status=400)

    rows = (
        [
            t.title,
            t.project.name,
            t.user.get_full_name() or t.user.username,
            t.get_status_display(),
            t.due_at.isoformat() if t.due_at else '',
            t.completed_at.isoformat() if t.completed_at else '',
            t.url or '',
        ]
        for t in (tasks if isinstance(tasks, list) else tasks.iterator(chunk_size=EXPORT_CHUNK_SIZE))
    )
    header = ["标题", "项目", "用户", "状态", "截止", "完成时间", "URL"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename=\"tasks_admin.csv\"'
    log_action(request, 'export', f"tasks_admin count={total_count} q={q}")
    return response


@login_required
def sla_settings(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)
    current = get_sla_hours()
    thresholds = get_sla_thresholds()
    if request.method == 'POST':
        hours_str = (request.POST.get('sla_hours') or '').strip()
        amber_str = (request.POST.get('sla_amber') or '').strip()
        red_str = (request.POST.get('sla_red') or '').strip()
        try:
            hours = int(hours_str)
            amber = int(amber_str)
            red = int(red_str)
            if hours < 1 or amber < 1 or red < 1:
                raise ValueError("必须大于 0")
        except Exception:
            messages.error(request, "请输入有效的小时数（正整数）")
        else:
            SystemSetting.objects.update_or_create(key='sla_hours', defaults={'value': str(hours)})
            SystemSetting.objects.update_or_create(key='sla_thresholds', defaults={'value': json.dumps({'amber': amber, 'red': red})})
            messages.success(request, "SLA 提醒窗口与阈值已保存")
            log_action(request, 'update', f"sla_settings update hours={hours} amber={amber} red={red}")
            current = hours
            thresholds = {'amber': amber, 'red': red}
    return render(request, 'reports/sla_settings.html', {
        'sla_hours': current,
        'sla_amber': thresholds.get('amber'),
        'sla_red': thresholds.get('red'),
    })


@login_required
def admin_task_stats(request):
    manageable_project_ids = set(Project.objects.filter(managers=request.user, is_active=True).values_list('id', flat=True))
    is_admin = has_manage_permission(request.user)
    if not is_admin and not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")

    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    date_str = request.GET.get('date')
    
    # New filters
    start_str = request.GET.get('start')
    end_str = request.GET.get('end')
    q = request.GET.get('q')
    role = request.GET.get('role')

    today = timezone.localdate()
    # Priority: Date Range > Single Date > Today
    # But logic uses 'query_date' for "Missing Reports" specifically.
    query_date = parse_date(date_str) if date_str else today
    
    start_date = parse_date(start_str) if start_str else None
    end_date = parse_date(end_str) if end_str else None

    # Base QuerySets
    tasks_qs = Task.objects.select_related('project', 'user')
    reports_qs = DailyReport.objects.select_related('user').prefetch_related('projects')

    # Apply permissions
    if not is_admin:
        tasks_qs = tasks_qs.filter(project_id__in=manageable_project_ids)
        reports_qs = reports_qs.filter(projects__id__in=manageable_project_ids)

    # Apply filters
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if is_admin or pid in manageable_project_ids:
            tasks_qs = tasks_qs.filter(project_id=pid)
            reports_qs = reports_qs.filter(projects__id=pid)
        else:
            tasks_qs = tasks_qs.none()
            reports_qs = reports_qs.none()
    
    if user_id and user_id.isdigit():
        uid = int(user_id)
        tasks_qs = tasks_qs.filter(user_id=uid)
        reports_qs = reports_qs.filter(user_id=uid)

    # Name Search (User or Task Title?) - Usually User for stats
    if q:
        user_q = Q(user__username__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        tasks_qs = tasks_qs.filter(user_q)
        reports_qs = reports_qs.filter(user_q)
        
    # Role Filter
    if role and role in dict(Profile.ROLE_CHOICES):
        tasks_qs = tasks_qs.filter(user__profile__position=role)
        reports_qs = reports_qs.filter(role=role)

    # Date Range Filter (For Stats)
    # If start/end provided, filter tasks by created_at (or due_at? created_at is safer for general stats)
    if start_date and end_date:
        tasks_qs = tasks_qs.filter(created_at__date__range=[start_date, end_date])
        # For reports, filter by date field
        reports_qs = reports_qs.filter(date__range=[start_date, end_date])
    elif start_date:
        tasks_qs = tasks_qs.filter(created_at__date__gte=start_date)
        reports_qs = reports_qs.filter(date__gte=start_date)
    elif end_date:
        tasks_qs = tasks_qs.filter(created_at__date__lte=end_date)
        reports_qs = reports_qs.filter(date__lte=end_date)

    # --- 1. Task Metrics ---
    total = tasks_qs.count()
    completed = tasks_qs.filter(status='completed').count()
    overdue = tasks_qs.filter(status='overdue').count()
    completion_rate = (completed / total * 100) if total else 0
    overdue_rate = (overdue / total * 100) if total else 0

    # --- 2. Report Metrics ---
    total_reports = reports_qs.count()
    last_report = reports_qs.order_by('-created_at').first()
    
    # Missing Reports (Today/Query Date)
    User = get_user_model()
    if is_admin:
        relevant_projects = Project.objects.filter(is_active=True)
    else:
        relevant_projects = Project.objects.filter(id__in=manageable_project_ids, is_active=True)
    
    if project_id and project_id.isdigit():
        relevant_projects = relevant_projects.filter(id=int(project_id))
    
    # Get users who are members of relevant projects
    # Note: This might be slow for large datasets, consider optimizing
    relevant_users = User.objects.filter(
        Q(project_memberships__in=relevant_projects) | 
        Q(managed_projects__in=relevant_projects) |
        Q(owned_projects__in=relevant_projects)
    ).distinct()
    
    if user_id and user_id.isdigit():
        relevant_users = relevant_users.filter(id=int(user_id))

    reports_today = reports_qs.filter(created_at__date=query_date)
    reported_user_ids = set(reports_today.values_list('user_id', flat=True))
    
    missing_users = relevant_users.exclude(id__in=reported_user_ids)
    missing_count = missing_users.count()

    if request.GET.get('remind') == '1':
        # Optimized email reminder logic using send_mass_mail
        from django.core.mail import send_mass_mail
        
        messages_to_send = []
        subject = f"[提醒] 请提交今日日报 ({today})"
        from_email = settings.DEFAULT_FROM_EMAIL
        
        for u in missing_users:
            if u.email:
                message = f"Hi {u.get_full_name() or u.username},\n\n请记得提交今天的日报。\nPlease submit your daily report for today."
                messages_to_send.append((subject, message, from_email, [u.email]))
        
        sent_count = 0
        if messages_to_send:
            try:
                # send_mass_mail opens a single connection for all messages
                sent_count = send_mass_mail(tuple(messages_to_send), fail_silently=True)
            except Exception as e:
                logger.error(f"Failed to send mass reminder emails: {e}")
        
        messages.success(request, f"已向 {sent_count} 位用户发送催报邮件 / Sent reminders to {sent_count} users")
        return redirect(request.path)

    metrics = {
        'missing_today': missing_count,
        'total_reports': total_reports,
        'last_date': last_report.created_at.date() if last_report else None,
        'total_projects': relevant_projects.count(),
    }

    # --- 3. Charts Data ---
    # Trend (Last 14 days)
    trend_labels = []
    trend_data = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        trend_labels.append(d.strftime('%m-%d'))
        c = reports_qs.filter(created_at__date=d).count()
        trend_data.append(c)
    
    report_trend = {'labels': trend_labels, 'data': trend_data}

    # Role Distribution
    role_counts_raw = list(reports_qs.values_list('role').annotate(c=Count('id')).order_by('-c'))
    role_map = dict(DailyReport.ROLE_CHOICES)
    role_counts = [(role_map.get(r, r), c) for r, c in role_counts_raw]

    # --- 4. Urgent SLA Tasks ---
    # Fetch settings
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None

    urgent_tasks = []
    candidates = tasks_qs.filter(status__in=['pending', 'in_progress'], due_at__isnull=False)
    # Limit candidates to avoid performance hit
    candidates = candidates.order_by('due_at')[:50] 
    
    for t in candidates:
         info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
         if info['level'] in ('red', 'orange'):
             t.sla_info = info
             urgent_tasks.append(t)
    urgent_tasks.sort(key=lambda x: x.sla_info['remaining_hours'])
    sla_urgent_tasks = urgent_tasks[:10]

    # --- 5. Missing Projects Table ---
    # Group missing users by project
    missing_projects_map = {}
    # Prefetch to reduce queries
    for u in missing_users.prefetch_related('project_memberships'):
        # Find intersection of user's projects and relevant_projects
        user_pids = set(u.project_memberships.values_list('id', flat=True))
        # Also check owned/managed? usually project_memberships covers members
        relevant_pids = set(relevant_projects.values_list('id', flat=True))
        common = user_pids.intersection(relevant_pids)
        
        for pid in common:
            if pid not in missing_projects_map:
                pname = relevant_projects.get(id=pid).name
                missing_projects_map[pid] = {'project': pname, 'users': []}
            missing_projects_map[pid]['users'].append({'name': u.get_full_name() or u.username})
            
    missing_projects = []
    for pid, data in missing_projects_map.items():
        missing_projects.append({
            'project': data['project'],
            'missing_count': len(data['users']),
            'users': data['users']
        })
    missing_projects.sort(key=lambda x: x['missing_count'], reverse=True)
    missing_projects = missing_projects[:10]

    # --- 6. Stats Tables (Project/User) ---
    project_stats_qs = tasks_qs.values('project__id', 'project__name').annotate(
        total=models.Count('id'),
        completed=models.Count('id', filter=models.Q(status='completed')),
        overdue=models.Count('id', filter=models.Q(status='overdue'))
    ).order_by('project__name')
    
    user_stats_qs = tasks_qs.values('user__id', 'user__username', 'user__first_name', 'user__last_name').annotate(
        total=models.Count('id'),
        completed=models.Count('id', filter=models.Q(status='completed')),
        overdue=models.Count('id', filter=models.Q(status='overdue'))
    ).order_by('user__username')

    project_stats = []
    for row in project_stats_qs:
        total_p = row['total']
        comp_p = row['completed']
        ovd_p = row['overdue']
        project_stats.append({
            'project': row['project__name'] or '—',
            'total': total_p,
            'completed': comp_p,
            'overdue': ovd_p,
            'completion_rate': (comp_p / total_p * 100) if total_p else 0,
            'overdue_rate': (ovd_p / total_p * 100) if total_p else 0,
            'sla_rate': 0, # Placeholder, calculation is expensive without pre-aggregation
        })

    user_stats = []
    for row in user_stats_qs:
        total_u = row['total']
        comp_u = row['completed']
        ovd_u = row['overdue']
        full_name = ((row['user__first_name'] or '') + ' ' + (row['user__last_name'] or '')).strip()
        user_stats.append({
            'username': row['user__username'],
            'full_name': full_name,
            'total': total_u,
            'completed': comp_u,
            'overdue': ovd_u,
            'completion_rate': (comp_u / total_u * 100) if total_u else 0,
            'overdue_rate': (ovd_u / total_u * 100) if total_u else 0,
        })

    # Choices for filters
    if is_admin:
        user_choices = User.objects.select_related('profile').all().order_by('username')
        project_choices = Project.objects.filter(is_active=True).order_by('name')
    else:
        project_choices = Project.objects.filter(id__in=manageable_project_ids).order_by('name')
        user_choices = User.objects.select_related('profile').filter(
            Q(project_memberships__id__in=manageable_project_ids) |
            Q(managed_projects__id__in=manageable_project_ids) |
            Q(owned_projects__id__in=manageable_project_ids)
        ).distinct().order_by('username')
        
    if project_id and project_id.isdigit():
        pid = int(project_id)
        project_choices = project_choices.filter(id=pid)
        member_ids = set(
            User.objects.filter(
                Q(project_memberships__id=pid) | Q(managed_projects__id=pid) | Q(owned_projects__id=pid)
            ).values_list('id', flat=True)
        )
        user_choices = user_choices.filter(id__in=member_ids) if member_ids else user_choices.none()

    return render(request, 'reports/admin_task_stats.html', {
        'total': total,
        'completed': completed,
        'overdue': overdue,
        'completion_rate': completion_rate,
        'overdue_rate': overdue_rate,
        'project_stats': project_stats,
        'user_stats': user_stats,
        'metrics': metrics,
        'report_trend': report_trend,
        'role_counts': role_counts,
        'missing_projects': missing_projects,
        'sla_urgent_tasks': sla_urgent_tasks,
        'project_id': int(project_id) if project_id and project_id.isdigit() else '',
        'user_id': int(user_id) if user_id and user_id.isdigit() else '',
        'projects': project_choices,
        'users': user_choices,
        'today': today.isoformat(),
        'sla_remind': DEFAULT_SLA_REMIND,
        'start': start_date,
        'end': end_date,
        'role_filter': role,
        'report_roles': Profile.ROLE_CHOICES,
    })


@login_required
def admin_task_stats_export(request):
    manageable_project_ids = set(Project.objects.filter(managers=request.user, is_active=True).values_list('id', flat=True))
    is_admin = has_manage_permission(request.user)
    if not is_admin and not manageable_project_ids:
        return _admin_forbidden(request, "需要管理员或项目管理员权限 / Admin or project manager required")

    project_id = request.GET.get('project')
    user_id = request.GET.get('user')
    
    start_str = request.GET.get('start')
    end_str = request.GET.get('end')
    q = request.GET.get('q')
    role = request.GET.get('role')

    start_date = parse_date(start_str) if start_str else None
    end_date = parse_date(end_str) if end_str else None

    tasks = Task.objects.select_related('project', 'user')
    if not is_admin:
        tasks = tasks.filter(project_id__in=manageable_project_ids)
    if project_id and project_id.isdigit():
        pid = int(project_id)
        if is_admin or pid in manageable_project_ids:
            tasks = tasks.filter(project_id=pid)
        else:
            tasks = tasks.none()
    if user_id and user_id.isdigit():
        tasks = tasks.filter(user_id=int(user_id))

    if q:
        tasks = tasks.filter(Q(user__username__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))
    if role and role in dict(Profile.ROLE_CHOICES):
        tasks = tasks.filter(user__profile__position=role)
    
    if start_date and end_date:
        tasks = tasks.filter(created_at__date__range=[start_date, end_date])
    elif start_date:
        tasks = tasks.filter(created_at__date__gte=start_date)
    elif end_date:
        tasks = tasks.filter(created_at__date__lte=end_date)

    rows = []
    grouped = tasks.values('project__name', 'user__username', 'user__first_name', 'user__last_name').annotate(
        total=models.Count('id'),
        completed=models.Count('id', filter=models.Q(status='completed')),
        overdue=models.Count('id', filter=models.Q(status='overdue'))
    )
    for g in grouped:
        total = g['total']
        comp = g['completed']
        ovd = g['overdue']
        comp_rate = f"{(comp/total*100):.1f}%" if total else "0%"
        ovd_rate = f"{(ovd/total*100):.1f}%" if total else "0%"
        rows.append([
            g['project__name'] or '',
            g['user__username'],
            f"{g['user__first_name'] or ''} {g['user__last_name'] or ''}".strip(),
            total,
            comp,
            ovd,
            comp_rate,
            ovd_rate,
        ])

    header = ["项目", "用户名", "姓名", "总任务数", "已完成", "逾期", "完成率", "逾期率"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="task_stats.csv"'
    log_action(request, 'export', f"task_stats project={project_id} user={user_id}")
    return response

@login_required
def admin_task_create(request):
    user = request.user
    is_admin = has_manage_permission(user)
    manageable_project_ids = set(
        Project.objects.filter(
            is_active=True,
            managers=user,
        ).values_list('id', flat=True)
    ) | set(
        Project.objects.filter(is_active=True, owner=user).values_list('id', flat=True)
    )
    if not is_admin and not manageable_project_ids:
        return _admin_forbidden(request)

    projects_qs = Project.objects.filter(is_active=True)
    if not is_admin:
        projects_qs = projects_qs.filter(id__in=manageable_project_ids)
    projects = projects_qs.annotate(task_count=Count('tasks')).order_by('-task_count', 'name')
    User = get_user_model()
    user_objs = list(User.objects.all().order_by('username'))
    existing_urls = [u for u in Task.objects.exclude(url='').values_list('url', flat=True).distinct()]

    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        url = (request.POST.get('url') or '').strip()
        content = (request.POST.get('content') or '').strip()
        project_id = request.POST.get('project')
        user_id = request.POST.get('user')
        status = request.POST.get('status') or 'pending'
        due_at_str = request.POST.get('due_at')

        errors = []
        if not title:
            errors.append("请输入任务标题")
        if not url and not content:
            errors.append("任务内容需填写：请选择 URL 或填写文本内容")
        if status not in dict(Task.STATUS_CHOICES):
            errors.append("请选择有效的状态")
        project = None
        target_user = None
        if project_id and project_id.isdigit():
            project = Project.objects.filter(id=int(project_id)).first()
        if not project or (not is_admin and project.id not in manageable_project_ids):
            errors.append("请选择项目")
        if user_id and user_id.isdigit():
            target_user = User.objects.filter(id=int(user_id)).first()
        if not target_user:
            errors.append("请选择目标用户")

        due_at = None
        if due_at_str:
            try:
                parsed = datetime.fromisoformat(due_at_str)
                due_at = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
            except ValueError:
                errors.append("完成时间格式不正确，请使用日期时间选择器")

        if errors:
            return render(request, 'reports/admin_task_form.html', {
                'errors': errors,
                'projects': projects,
                'users': user_objs,
                'task_status_choices': Task.STATUS_CHOICES,
                'existing_urls': existing_urls,
                'form_values': {'title': title, 'url': url, 'content': content, 'project_id': project_id, 'user_id': user_id, 'status': status, 'due_at': due_at_str},
            })

        task = Task.objects.create(
            title=title,
            url=url,
            content=content,
            project=project,
            user=target_user,
            status=status,
            due_at=due_at,
        )

        # Handle attachments
        for f in request.FILES.getlist('attachments'):
            TaskAttachment.objects.create(
                task=task,
                user=request.user,
                file=f
            )

        log_action(request, 'create', f"task {task.id}")
        return redirect('reports:admin_task_list')

    return render(request, 'reports/admin_task_form.html', {
        'projects': projects,
        'users': user_objs,
        'task_status_choices': Task.STATUS_CHOICES,
        'existing_urls': existing_urls,
        'form_values': {
            'project_id': request.GET.get('project_id'),
        },
    })


@login_required
def admin_reports_export(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    reports, role, start_date, end_date = _filtered_reports(request)

    if not start_date or not end_date:
        return HttpResponse("请提供开始和结束日期后再导出。", status=400)

    username = (request.GET.get('username') or '').strip()
    project_id = request.GET.get('project')
    status = (request.GET.get('status') or '').strip()
    if username:
        reports = reports.filter(
            Q(user__username__icontains=username) |
            Q(user__first_name__icontains=username) |
            Q(user__last_name__icontains=username)
        )
    if project_id and project_id.isdigit():
        reports = reports.filter(projects__id=int(project_id))
    if status in dict(DailyReport.STATUS_CHOICES):
        reports = reports.filter(status=status)

    if not (username or project_id):
        return HttpResponse("请至少指定用户名或项目过滤后再导出。", status=400)

    total_count = reports.count()
    if total_count > MAX_EXPORT_ROWS:
        if request.GET.get('queue') != '1':
            return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters. 如需排队导出，请带 queue=1 参数 / Use queue=1 to enqueue export.", status=400)
        job = _create_export_job(request.user, 'admin_reports_filtered')
        try:
            _generate_export_file(
                job,
                ["日期", "角色", "项目", "用户", "状态", "摘要", "创建时间"],
                (
                    [
                        str(r.date),
                        r.get_role_display(),
                        r.project_names or "",
                        r.user.get_full_name() or r.user.username,
                        r.get_status_display(),
                        r.summary or "",
                        timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
                    ]
                    for r in reports.iterator(chunk_size=EXPORT_CHUNK_SIZE)
                )
            )
            return JsonResponse({'queued': True, 'job_id': job.id})
        except Exception as e:
            job.status = 'failed'
            job.message = str(e)
            job.save(update_fields=['status', 'message', 'updated_at'])
            return JsonResponse({'error': 'export failed'}, status=500)

    rows = (
        [
            str(r.date),
            r.get_role_display(),
            r.project_names or "",
            r.user.get_full_name() or r.user.username,
            r.get_status_display(),
            r.summary or "",
            timezone.localtime(r.created_at).strftime("%Y-%m-%d %H:%M"),
        ]
        for r in reports.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["日期", "角色", "项目", "作者", "状态", "摘要", "创建时间"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="daily_reports.csv"'
    log_action(request, 'export', f"daily_reports count={reports.count()} role={role} start={start_date} end={end_date} username={username} project={project_id}")
    return response


@login_required
def project_list(request):
    projects, q, start_date, end_date, owner = _filtered_projects(request)
    
    # Filter by phase
    phase_id = request.GET.get('phase')
    if phase_id and phase_id.isdigit():
        projects = projects.filter(current_phase_id=int(phase_id))
        
    projects = projects.annotate(member_count=Count('members', distinct=True), report_count=Count('reports', distinct=True))
    paginator = Paginator(projects, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    manageable_ids = {p.id for p in page_obj if has_project_manage_permission(request.user, p)}
    
    phases = ProjectPhaseConfig.objects.filter(is_active=True)
    
    context = {
        'projects': page_obj,
        'page_obj': page_obj,
        'q': q,
        'start_date': start_date,
        'end_date': end_date,
        'owner': owner,
        'total_count': projects.count(),
        'manageable_ids': manageable_ids,
        'phases': phases,
        'phase_id': int(phase_id) if phase_id and phase_id.isdigit() else '',
    }
    return render(request, 'reports/project_list.html', context)


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
    active_projects = Project.objects.filter(is_active=True).prefetch_related('members', 'managers', 'reports')
    if project_filter and project_filter.isdigit():
        active_projects = active_projects.filter(id=int(project_filter))
    cache_key = f"stats_missing_{target_date}_{project_filter}_{role_filter}"
    cached = cache.get(cache_key)
    if cached:
        missing_projects, total_missing = cached
    else:
        missing_projects = []
        total_missing = 0
        for p in active_projects:
            expected_users = set(p.members.values_list('id', flat=True)) | set(p.managers.values_list('id', flat=True))
            if p.owner_id:
                expected_users.add(p.owner_id)
            missing_ids = [uid for uid in expected_users if uid not in todays_user_ids]
            if not missing_ids:
                continue
            user_qs = get_user_model().objects.select_related('profile').filter(id__in=missing_ids)
            if role_filter in dict(Profile.ROLE_CHOICES):
                user_qs = user_qs.filter(profile__position=role_filter)
                missing_ids = list(user_qs.values_list('id', flat=True))
            if not missing_ids:
                continue
            total_missing += len(missing_ids)
            last_report_dates = DailyReport.objects.filter(user_id__in=missing_ids, status='submitted').values('user_id').annotate(last_date=models.Max('date'))
            last_map = {item['user_id']: item['last_date'] for item in last_report_dates}
            users = user_qs
            missing_projects.append({
                'project': p.name,
                'project_id': p.id,
                'missing_count': len(missing_ids),
                'users': [
                    {
                        'name': u.get_full_name() or u.username,
                        'last_date': last_map.get(u.id)
                    } for u in users
                ],
                'last_map': last_map,
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
            completed=Count('tasks', filter=Q(tasks__status='completed')),
            overdue=Count('tasks', filter=Q(tasks__status='overdue')),
            within_sla=Count('tasks', filter=Q(
                tasks__status='completed',
                tasks__due_at__isnull=False,
                tasks__completed_at__isnull=False,
                tasks__completed_at__lte=models.F('tasks__due_at')
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
    
    # Pre-fetch SLA settings once
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None

    for t in Task.objects.select_related('project', 'user').exclude(status='completed'):
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
    if not has_manage_permission(request.user):
        messages.error(request, "需要管理员权限 / Admin access required")
        return render(request, '403.html', status=403)
    start_date = parse_date(request.GET.get('start') or '') or None
    end_date = parse_date(request.GET.get('end') or '') or None
    project_param = request.GET.get('project')
    role_param = (request.GET.get('role') or '').strip()
    q = request.GET.get('q')
    project_filter = int(project_param) if project_param and project_param.isdigit() else None
    role_filter = role_param if role_param in dict(Profile.ROLE_CHOICES) else None

    stats = _performance_stats(start_date=start_date, end_date=end_date, project_id=project_filter, role_filter=role_filter, q=q)
    urgent_tasks = stats.get('overall_overdue', Task.objects.filter(status='overdue').count())
    total_tasks = stats.get('overall_total', Task.objects.count())
    
    # Pre-fetch SLA settings once
    cfg_sla_hours = SystemSetting.objects.filter(key='sla_hours').first()
    sla_hours_val = int(cfg_sla_hours.value) if cfg_sla_hours and cfg_sla_hours.value.isdigit() else None
    cfg_thresholds = SystemSetting.objects.filter(key='sla_thresholds').first()
    sla_thresholds_val = cfg_thresholds.value if cfg_thresholds else None
    
    thresholds = get_sla_thresholds(system_setting_value=sla_thresholds_val)
    sla_only = request.GET.get('sla_only') == '1'
    sla_urgent_tasks = []
    for t in Task.objects.select_related('project', 'user').exclude(status='completed'):
        info = calculate_sla_info(t, sla_hours_setting=sla_hours_val, sla_thresholds_setting=sla_thresholds_val)
        if info and info.get('status') in ('tight', 'overdue'):
            t.sla_info = info
            sla_urgent_tasks.append(t)
    sla_urgent_tasks.sort(key=lambda t: (
        t.sla_info.get('sort', 3),
        t.sla_info.get('remaining_hours') if t.sla_info.get('remaining_hours') is not None else 9999,
        -t.created_at.timestamp(),
    ))

    if request.GET.get('send_weekly') == '1':
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
        'projects': Project.objects.filter(is_active=True).order_by('name'),
        'report_roles': Profile.ROLE_CHOICES,
        'user_stats_page': Paginator(stats.get('user_stats', []), 10).get_page(request.GET.get('upage')),
    })


@login_required
def performance_export(request):
    """导出绩效看板数据，scope=project|role|user|streak。"""
    if not has_manage_permission(request.user):
        messages.error(request, "需要管理员权限 / Admin access required")
        return render(request, '403.html', status=403)
    scope = (request.GET.get('scope') or 'project').strip()
    start_date = parse_date(request.GET.get('start') or '') or None
    end_date = parse_date(request.GET.get('end') or '') or None
    project_param = request.GET.get('project')
    role_param = (request.GET.get('role') or '').strip()
    q = request.GET.get('q')
    project_filter = int(project_param) if project_param and project_param.isdigit() else None
    role_filter = role_param if role_param in dict(Profile.ROLE_CHOICES) else None
    stats = _performance_stats(start_date=start_date, end_date=end_date, project_id=project_filter, role_filter=role_filter, q=q)

    if scope == 'role':
        rows = [
            [
                item['role_label'],
                item['total'],
                item['completed'],
                item['overdue'],
                f"{item['completion_rate']:.1f}%",
                f"{item['overdue_rate']:.1f}%",
                f"{item['sla_on_time_rate']:.1f}%",
                item['lead_time_p50'] if item['lead_time_p50'] is not None else '',
                item['lead_time_avg'] if item['lead_time_avg'] is not None else '',
            ]
            for item in stats['role_stats']
        ]
        header = ["角色 / Role", "任务总数", "完成", "逾期", "完成率", "逾期率", "SLA 准时率", "Lead Time 中位(h)", "Lead Time 平均(h)"]
        filename = "performance_role.csv"
    elif scope == 'user':
        rows = [
            [
                item['user_label'],
                item['total'],
                item['completed'],
                item['overdue'],
                f"{item['completion_rate']:.1f}%",
                f"{item['overdue_rate']:.1f}%",
                f"{item['sla_on_time_rate']:.1f}%",
                item['lead_time_p50'] if item['lead_time_p50'] is not None else '',
                item['lead_time_avg'] if item['lead_time_avg'] is not None else '',
            ]
            for item in stats['user_stats']
        ]
        header = ["用户 / User", "任务总数", "完成", "逾期", "完成率", "逾期率", "SLA 准时率", "Lead Time 中位(h)", "Lead Time 平均(h)"]
        filename = "performance_user.csv"
    elif scope == 'streak':
        rows = [
            [
                item['role_label'],
                item['avg_streak'],
                item['max_streak'],
            ]
            for item in stats['role_streaks']
        ]
        header = ["角色 / Role", "平均连签天数 / Avg streak", "最高连签天数 / Max streak"]
        filename = "performance_streak.csv"
    else:
        rows = [
            [
                item['project'],
                item['total'],
                item['completed'],
                item['overdue'],
                f"{item['completion_rate']:.1f}%",
                f"{item['overdue_rate']:.1f}%",
                f"{item['sla_on_time_rate']:.1f}%",
                item['lead_time_p50'] if item['lead_time_p50'] is not None else '',
                item['lead_time_avg'] if item['lead_time_avg'] is not None else '',
            ]
            for item in stats['project_stats']
        ]
        header = ["项目 / Project", "任务总数", "完成", "逾期", "完成率", "逾期率", "SLA 准时率", "Lead Time 中位(h)", "Lead Time 平均(h)"]
        filename = "performance_project.csv"

    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    log_action(request, 'export', f"performance scope={scope}")
    return response


@login_required
def stats_export(request):
    """导出统计相关数据：type=missing|project_sla|user_sla"""
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    export_type = (request.GET.get('type') or 'missing').strip()
    target_date = parse_date(request.GET.get('date') or '') or timezone.localdate()

    if export_type == 'project_sla':
        tasks_qs = Task.objects.select_related('project')
        projects = Project.objects.filter(is_active=True).order_by('name')
        rows = []
        for p in projects:
            total = tasks_qs.filter(project=p).count()
            completed = tasks_qs.filter(project=p, status='completed').count()
            overdue = tasks_qs.filter(project=p, status='overdue').count()
            within_sla = tasks_qs.filter(
                project=p,
                status='completed',
                due_at__isnull=False,
                completed_at__isnull=False,
                completed_at__lte=models.F('due_at')
            ).count()
            sla_rate = (within_sla / completed * 100) if completed else 0
            rows.append([
                p.name,
                total,
                completed,
                overdue,
                within_sla,
                f"{sla_rate:.1f}%",
            ])
        header = ["项目", "总任务", "已完成", "逾期", "SLA 内完成", "达成率"]
        filename = f"project_sla_{target_date}.csv"

    elif export_type == 'user_sla':
        tasks_qs = Task.objects.select_related('user')
        grouped = tasks_qs.values('user__username', 'user__first_name', 'user__last_name').annotate(
            total=models.Count('id'),
            completed=models.Count('id', filter=models.Q(status='completed')),
            overdue=models.Count('id', filter=models.Q(status='overdue')),
        )
        rows = []
        for g in grouped:
            total = g['total']
            completed = g['completed']
            overdue = g['overdue']
            rows.append([
                g['user__username'],
                f"{(g['user__first_name'] or '')} {(g['user__last_name'] or '')}".strip(),
                total,
                completed,
                overdue,
                f"{(completed/total*100):.1f}%" if total else "0%",
                f"{(overdue/total*100):.1f}%" if total else "0%",
            ])
        header = ["用户名", "姓名", "总任务", "已完成", "逾期", "完成率", "逾期率"]
        filename = f"user_sla_{target_date}.csv"

    else:
        # missing
        qs = DailyReport.objects.filter(date=target_date)
        todays_user_ids = set(qs.values_list('user_id', flat=True))
        active_projects = Project.objects.filter(is_active=True).prefetch_related('members', 'managers')
        rows = []
        for p in active_projects:
            expected_users = set(p.members.values_list('id', flat=True)) | set(p.managers.values_list('id', flat=True))
            if p.owner_id:
                expected_users.add(p.owner_id)
            missing_ids = [uid for uid in expected_users if uid not in todays_user_ids]
            if missing_ids:
                users = get_user_model().objects.filter(id__in=missing_ids)
                rows.append([
                    p.name,
                    len(missing_ids),
                    ", ".join([u.get_full_name() or u.username for u in users]),
                ])
        header = ["项目", "缺报人数", "名单"]
        filename = f"missing_reports_{target_date}.csv"

    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename=\"{filename}\"'
    log_action(request, 'export', f"stats_export type={export_type} date={target_date}")
    return response


@login_required
def audit_logs(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    action = (request.GET.get('action') or '').strip()
    method = (request.GET.get('method') or '').strip()
    user_q = (request.GET.get('user') or '').strip()
    path_q = (request.GET.get('path') or '').strip()

    qs = AuditLog.objects.select_related('user').order_by('-created_at')
    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)
    if action:
        qs = qs.filter(action=action)
    if method:
        qs = qs.filter(method__iexact=method)
    if user_q:
        qs = qs.filter(Q(user__username__icontains=user_q) | Q(user__first_name__icontains=user_q) | Q(user__last_name__icontains=user_q))
    if path_q:
        qs = qs.filter(path__icontains=path_q)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'logs': page_obj,
        'page_obj': page_obj,
        'start_date': start_date,
        'end_date': end_date,
        'action': action,
        'method': method,
        'user_q': user_q,
        'path_q': path_q,
        'actions': AuditLog.ACTION_CHOICES,
    }
    return render(request, 'reports/audit_logs.html', context)


@login_required
def audit_logs_export(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    action = (request.GET.get('action') or '').strip()
    method = (request.GET.get('method') or '').strip()
    user_q = (request.GET.get('user') or '').strip()
    path_q = (request.GET.get('path') or '').strip()

    qs = AuditLog.objects.select_related('user').order_by('-created_at')
    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)
    if action:
        qs = qs.filter(action=action)
    if method:
        qs = qs.filter(method__iexact=method)
    if user_q:
        qs = qs.filter(Q(user__username__icontains=user_q) | Q(user__first_name__icontains=user_q) | Q(user__last_name__icontains=user_q))
    if path_q:
        qs = qs.filter(path__icontains=path_q)

    if not (start_date and end_date):
        return HttpResponse("请提供开始和结束日期后再导出。", status=400)
    if qs.count() > MAX_EXPORT_ROWS:
        return HttpResponse("数据量过大，请缩小筛选范围后再导出。", status=400)

    rows = (
        [
            log.created_at.astimezone(timezone.get_current_timezone()).strftime("%Y-%m-%d %H:%M"),
            log.user.get_full_name() or log.user.username if log.user else "匿名",
            log.get_action_display(),
            log.method,
            log.path,
            log.ip or "",
            log.extra or "",
        ]
        for log in qs.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["时间", "用户", "动作", "方法", "路径", "IP", "备注"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="audit_logs.csv"'
    log_action(request, 'export', f"audit_logs count={qs.count()} action={action} method={method}")
    return response


@login_required
def project_detail(request, pk: int):
    project = get_object_or_404(Project.objects.select_related('owner', 'current_phase').prefetch_related('members__profile', 'managers__profile'), pk=pk)
    recent_reports = project.reports.select_related('user').order_by('-date')[:5]
    tasks_qs = Task.objects.filter(project=project)
    total = tasks_qs.count()
    completed = tasks_qs.filter(status='completed').count()
    overdue = tasks_qs.filter(status='overdue').count()
    within_sla = tasks_qs.filter(
        status='completed',
        due_at__isnull=False,
        completed_at__isnull=False,
        completed_at__lte=models.F('due_at')
    ).count()
    sla_rate = (within_sla / completed * 100) if completed else 0
    
    # Task List Logic
    tasks_qs = Task.objects.filter(project=project).select_related('user', 'user__profile')
    
    task_status = request.GET.get('task_status')
    if task_status in dict(Task.STATUS_CHOICES):
        tasks_qs = tasks_qs.filter(status=task_status)
    elif task_status == 'active':
        tasks_qs = tasks_qs.exclude(status__in=['completed', 'reopened']) # Assuming reopened is active? Or maybe just exclude completed
    
    task_sort = request.GET.get('task_sort')
    if task_sort == 'due_at':
        tasks_qs = tasks_qs.order_by('due_at', '-created_at')
    elif task_sort == '-due_at':
        tasks_qs = tasks_qs.order_by('-due_at', '-created_at')
    elif task_sort == 'priority':
        tasks_qs = tasks_qs.order_by('due_at') # Simple proxy for priority
    else:
        tasks_qs = tasks_qs.order_by('-created_at')

    paginator = Paginator(tasks_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate SLA info for displayed tasks
    for t in page_obj:
        t.sla_info = calculate_sla_info(t)

    phases = ProjectPhaseConfig.objects.filter(is_active=True)
    
    return render(request, 'reports/project_detail.html', {
        'project': project,
        'recent_reports': recent_reports,
        'can_manage': has_project_manage_permission(request.user, project),
        'task_stats': {
            'total': total,
            'completed': completed,
            'overdue': overdue,
            'within_sla': within_sla,
            'sla_rate': sla_rate,
        },
        'phases': phases,
        'tasks': page_obj,
        'task_status': task_status,
        'task_sort': task_sort,
        'task_status_choices': Task.STATUS_CHOICES,
    })


@login_required
def project_create(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            log_action(request, 'create', f"project {project.id} {project.code}")
            return redirect('reports:project_detail', pk=project.pk)
    else:
        form = ProjectForm()
    return render(request, 'reports/project_form.html', {'form': form, 'mode': 'create'})


@login_required
def project_edit(request, pk: int):
    project = get_object_or_404(Project, pk=pk)
    if not has_project_manage_permission(request.user, project):
        return _admin_forbidden(request, "需要管理员权限 / Admin or project manager required")

    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            project = form.save()
            log_action(request, 'update', f"project {project.id} {project.code}")
            _invalidate_stats_cache()
            return redirect('reports:project_detail', pk=project.pk)
    else:
        form = ProjectForm(instance=project)
    return render(request, 'reports/project_form.html', {'form': form, 'mode': 'edit', 'project': project})


@login_required
def project_delete(request, pk: int):
    project = get_object_or_404(Project, pk=pk)
    if not has_project_manage_permission(request.user, project):
        return _admin_forbidden(request, "需要管理员权限 / Admin or project manager required")
    if request.method == 'POST':
        project.is_active = False
        project.save(update_fields=['is_active'])
        log_action(request, 'delete', f"project {project.id} {project.code}")
        _invalidate_stats_cache()
        return redirect('reports:project_list')
    return render(request, 'reports/project_confirm_delete.html', {'project': project})


@login_required
def project_export(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)

    projects, q, start_date, end_date, owner = _filtered_projects(request)

    if not (q or start_date or end_date or owner):
        return HttpResponse("请至少提供搜索关键词、负责人或日期范围后再导出。", status=400)

    if projects.count() > MAX_EXPORT_ROWS:
        return HttpResponse("数据量过大，请缩小筛选范围后再导出 / Data too large, please narrow filters.", status=400)

    rows = (
        [
            p.name,
            p.code,
            p.owner.get_full_name() or p.owner.username if p.owner else "",
            ", ".join(p.members.values_list('username', flat=True)),
            ", ".join(p.managers.values_list('username', flat=True)),
            p.start_date.isoformat() if p.start_date else "",
            p.end_date.isoformat() if p.end_date else "",
            timezone.localtime(p.created_at).strftime("%Y-%m-%d %H:%M"),
            "已停用" if not p.is_active else "启用",
        ]
        for p in projects.iterator(chunk_size=EXPORT_CHUNK_SIZE)
    )
    header = ["名称", "代码", "负责人", "成员", "管理员", "开始日期", "结束日期", "创建时间", "状态"]
    response = StreamingHttpResponse(_stream_csv(rows, header), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="projects.csv"'
    log_action(request, 'export', f"projects count={projects.count()} q={q} start={start_date} end={end_date} owner={owner}")
    return response

def _send_phase_change_notification(project, old_phase, new_phase, changed_by):
    """
    发送项目阶段变更通知给负责人和管理员。
    Send phase change notification to project owner and admins.
    """
    subject = f"[{project.code}] 项目阶段变更通知 / Project Phase Changed"
    
    old_phase_name = old_phase.phase_name if old_phase else "N/A"
    new_phase_name = new_phase.phase_name if new_phase else "N/A"
    
    message = f"""
    项目名称 / Project: {project.name}
    变更时间 / Time: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}
    操作人 / By: {changed_by.get_full_name() or changed_by.username}
    
    阶段变更 / Phase Change:
    {old_phase_name} -> {new_phase_name}
    
    当前进度 / Current Progress: {project.overall_progress}%
    """
    
    recipients = set()
    if project.owner and project.owner.email:
        recipients.add(project.owner.email)
    
    # Add admins (superusers or managers)
    # Assuming 'managers' field on Project are also admins for this project
    for manager in project.managers.all():
        if manager.email:
            recipients.add(manager.email)
            
    # Also system admins
    for admin in get_user_model().objects.filter(is_superuser=True):
        if admin.email:
            recipients.add(admin.email)
            
    if recipients:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            list(recipients),
            fail_silently=True,
        )

@login_required
def project_phase_config_list(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)
        
    phases = ProjectPhaseConfig.objects.all()
    form = ProjectPhaseConfigForm()
    return render(request, 'reports/project_stage_config.html', {'phases': phases, 'form': form})

@login_required
def project_phase_config_create(request):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)
        
    if request.method == 'POST':
        form = ProjectPhaseConfigForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "阶段创建成功 / Phase created successfully")
            return redirect('reports:project_phase_config_list')
    else:
        form = ProjectPhaseConfigForm()
        
    return render(request, 'reports/project_stage_config.html', {'form': form, 'phases': ProjectPhaseConfig.objects.all()})

@login_required
def project_phase_config_update(request, pk):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)
        
    phase = get_object_or_404(ProjectPhaseConfig, pk=pk)
    if request.method == 'POST':
        form = ProjectPhaseConfigForm(request.POST, instance=phase)
        if form.is_valid():
            form.save()
            messages.success(request, "阶段更新成功 / Phase updated successfully")
            return redirect('reports:project_phase_config_list')
    else:
        form = ProjectPhaseConfigForm(instance=phase)
        
    return render(request, 'reports/project_stage_config.html', {'form': form, 'phases': ProjectPhaseConfig.objects.all(), 'editing': True, 'phase_id': pk})

@login_required
def project_phase_config_delete(request, pk):
    if not has_manage_permission(request.user):
        return _admin_forbidden(request)
        
    phase = get_object_or_404(ProjectPhaseConfig, pk=pk)
    if request.method == 'POST':
        phase.delete()
        messages.success(request, "阶段删除成功 / Phase deleted successfully")
        return redirect('reports:project_phase_config_list')
        
    return _friendly_forbidden(request, "Invalid method")

@login_required
def project_update_phase(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    
    # Check permission: Only Project Manager or higher (and Owner/Manager of the project)
    can_manage = has_manage_permission(request.user) or request.user == project.owner or project.managers.filter(pk=request.user.pk).exists()
    
    if not can_manage:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
        
    if request.method == 'POST':
        phase_id = request.POST.get('phase_id')
        try:
            new_phase = ProjectPhaseConfig.objects.get(pk=phase_id)
        except ProjectPhaseConfig.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': 'Phase not found'}, status=404)
            
        old_phase = project.current_phase
        
        if old_phase != new_phase:
            project.current_phase = new_phase
            project.overall_progress = new_phase.progress_percentage
            project.save()
            
            # Log change
            ProjectPhaseChangeLog.objects.create(
                project=project,
                old_phase=old_phase,
                new_phase=new_phase,
                changed_by=request.user
            )
            
            # Send notification
            _send_phase_change_notification(project, old_phase, new_phase, request.user)
            
            # Log audit
            log_action(request, 'update', f"Project {project.code} phase changed to {new_phase.phase_name}")
            
            return JsonResponse({
                'status': 'success', 
                'phase_name': new_phase.phase_name, 
                'progress': new_phase.progress_percentage
            })
            
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

@login_required
def project_phase_history(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    logs = project.phase_logs.all().select_related('old_phase', 'new_phase', 'changed_by')
    
    return render(request, 'reports/project_stage_history.html', {'project': project, 'logs': logs})

@login_required
def daily_report_batch_create(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            reports_data = data.get('reports', [])
            created_count = 0
            errors = []
            
            # Get user's role/position
            try:
                role = request.user.profile.position
            except (Profile.DoesNotExist, AttributeError):
                role = 'dev'

            for index, item in enumerate(reports_data):
                date_str = item.get('date')
                project_ids = item.get('projects', [])
                content = item.get('content', '')
                plan = item.get('plan', '')
                
                if not date_str:
                    errors.append(f"第 {index + 1} 行：日期不能为空")
                    continue
                
                try:
                    report_date = parse_date(date_str)
                    if not report_date:
                        raise ValueError
                except (ValueError, TypeError):
                    errors.append(f"第 {index + 1} 行：日期格式无效")
                    continue

                if DailyReport.objects.filter(user=request.user, date=report_date, role=role).exists():
                     errors.append(f"第 {index + 1} 行：{date_str} 的日报已存在")
                     continue
                
                # Create report
                report = DailyReport(
                    user=request.user,
                    date=report_date,
                    role=role,
                    today_work=content,
                    tomorrow_plan=plan,
                    status='submitted'
                )
                report.save()
                
                if project_ids:
                    # Filter valid project IDs
                    valid_projects = Project.objects.filter(id__in=project_ids)
                    report.projects.set(valid_projects)
                
                created_count += 1
            
            if errors:
                return JsonResponse({'success': False, 'message': '部分日报创建失败', 'errors': errors, 'created_count': created_count})
            
            return JsonResponse({'success': True, 'message': f'成功创建 {created_count} 份日报'})

        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'message': 'Method not allowed'}, status=405)

@login_required
def advanced_reporting(request):
    selected_project_id = request.GET.get('project_id')
    projects = Project.objects.filter(is_active=True)
    
    # Permission check for non-staff
    if not (request.user.is_staff or request.user.has_perm('reports.view_project')):
         projects = projects.filter(
             Q(members=request.user) | 
             Q(owner=request.user) | 
             Q(managers=request.user)
         ).distinct()

    project_id = None
    project_name = "所有项目"
    
    if selected_project_id and selected_project_id.isdigit():
        project_id = int(selected_project_id)
        # Verify access
        proj = projects.filter(id=project_id).first()
        if proj:
            project_name = proj.name
        else:
            project_id = None # Fallback if no access
            
    from .services.stats import get_advanced_report_data
    data = get_advanced_report_data(project_id)
    
    if data.get('burndown'):
        data['burndown']['project_name'] = project_name

    context = {
        'projects': projects,
        'selected_project_id': int(selected_project_id) if selected_project_id and selected_project_id.isdigit() else '',
        'gantt_data': data.get('gantt'),
        'burn_down_data': data.get('burndown'),
        'cfd_data': data.get('cfd'),
    }
    return render(request, 'reports/advanced_reporting.html', context)

@login_required
def task_upload_attachment(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    
    # Check permission
    can_manage = has_manage_permission(request.user) or task.user == request.user or task.project.owner == request.user
    
    if not can_manage:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
    
    if request.method == 'POST' and request.FILES.getlist('files'):
        uploaded_files = []
        for file in request.FILES.getlist('files'):
            attachment = TaskAttachment.objects.create(
                task=task,
                user=request.user,
                file=file
            )
            uploaded_files.append({
                'id': attachment.id,
                'name': file.name,
                'size': file.size,
                'url': attachment.file.url,
                'uploaded_by': attachment.user.get_full_name() or attachment.user.username,
                'created_at': attachment.created_at.strftime('%Y-%m-%d %H:%M')
            })
            
        return JsonResponse({'status': 'success', 'files': uploaded_files})
        
    return JsonResponse({'status': 'error', 'message': 'No files provided'}, status=400)

@login_required
def task_delete_attachment(request, attachment_id):
    attachment = get_object_or_404(TaskAttachment, pk=attachment_id)
    task = attachment.task
    
    # Check permission
    can_manage = has_manage_permission(request.user) or attachment.user == request.user or task.project.owner == request.user
    
    if not can_manage:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
        
    if request.method == 'POST':
        attachment.delete()
        return JsonResponse({'status': 'success'})
        
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)

@login_required
def project_upload_attachment(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    can_manage = has_manage_permission(request.user) or request.user == project.owner or project.managers.filter(pk=request.user.pk).exists() or project.members.filter(pk=request.user.pk).exists()
    
    if not can_manage:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
    
    if request.method == 'POST' and request.FILES.getlist('files'):
        uploaded_files = []
        for file in request.FILES.getlist('files'):
            attachment = ProjectAttachment.objects.create(
                project=project,
                uploaded_by=request.user,
                file=file,
                original_filename=file.name,
                file_size=file.size
            )
            uploaded_files.append({
                'id': attachment.id,
                'name': attachment.original_filename,
                'size': attachment.file_size,
                'url': attachment.file.url,
                'uploaded_by': attachment.uploaded_by.get_full_name() or attachment.uploaded_by.username,
                'created_at': attachment.created_at.strftime('%Y-%m-%d %H:%M')
            })
            
        return JsonResponse({'status': 'success', 'files': uploaded_files})
        
    return JsonResponse({'status': 'error', 'message': 'No files provided'}, status=400)

@login_required
def project_delete_attachment(request, attachment_id):
    attachment = get_object_or_404(ProjectAttachment, pk=attachment_id)
    project = attachment.project
    
    # Check permission (owner, manager, or the uploader)
    can_manage = has_manage_permission(request.user) or request.user == project.owner or project.managers.filter(pk=request.user.pk).exists() or attachment.uploaded_by == request.user
    
    if not can_manage:
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
        
    if request.method == 'POST':
        attachment.delete()
        return JsonResponse({'status': 'success'})
        
    return JsonResponse({'status': 'error', 'message': 'Invalid method'}, status=405)
