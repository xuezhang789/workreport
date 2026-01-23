from django.utils import timezone
from datetime import timedelta
import json
from django.conf import settings
from reports.models import Task, TaskSlaTimer, Project, SystemSetting

DEFAULT_SLA_REMIND = getattr(settings, 'SLA_REMIND_HOURS', 24)

def get_sla_hours(project: Project | None = None, system_setting_value=None):
    if project and project.sla_hours:
        return project.sla_hours
    
    if system_setting_value is not None:
        val = system_setting_value
    else:
        cfg = SystemSetting.objects.filter(key='sla_hours').first()
        val = int(cfg.value) if cfg else None

    if val is not None:
        try:
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
    return DEFAULT_SLA_REMIND


def _ensure_sla_timer(task: Task) -> TaskSlaTimer:
    timer = getattr(task, 'sla_timer', None)
    if timer:
        return timer
    return TaskSlaTimer.objects.create(task=task)


def _get_sla_timer_readonly(task: Task) -> TaskSlaTimer | None:
    """只读获取 timer，不创建新记录。"""
    return getattr(task, 'sla_timer', None)


def get_sla_thresholds(system_setting_value=None):
    """返回 SLA 阈值配置，单位小时。"""
    default_amber = getattr(settings, 'SLA_TIGHT_HOURS_DEFAULT', 6)
    default_red = getattr(settings, 'SLA_CRITICAL_HOURS_DEFAULT', 2)
    
    if system_setting_value:
        cfg_value = system_setting_value
    else:
        cfg = SystemSetting.objects.filter(key='sla_thresholds').first()
        cfg_value = cfg.value if cfg else None

    if cfg_value:
        try:
            data = json.loads(cfg_value)
            amber = int(data.get('amber', default_amber))
            red = int(data.get('red', default_red))
            return {'amber': amber, 'red': red}
        except Exception:
            pass
    return {'amber': default_amber, 'red': default_red}


def calculate_sla_info(task: Task, as_of=None, sla_hours_setting=None, sla_thresholds_setting=None):
    """
    计算 SLA 截止、剩余小时与颜色状态。
    status: normal/tight/overdue, paused: bool
    """
    now = as_of or timezone.now()
    timer = _get_sla_timer_readonly(task)
    paused_seconds = 0
    if timer:
        paused_seconds = timer.total_paused_seconds
        if task.status == 'on_hold' and timer.paused_at:
            paused_seconds += int((now - timer.paused_at).total_seconds())
    elif task.status in ('in_progress', 'on_hold'):
        # For calculation only, we don't strictly need to create it if it doesn't exist,
        # but the original logic did. To avoid side effects in a calculation function,
        # we should prefer readonly, but if logic depends on creation, we keep it.
        # Ideally, calculation shouldn't create DB records. 
        # However, let's keep consistent with original behavior but note the side effect.
        timer = _ensure_sla_timer(task)
        paused_seconds = timer.total_paused_seconds
        if task.status == 'on_hold' and timer.paused_at:
            paused_seconds += int((now - timer.paused_at).total_seconds())

    sla_deadline = None
    remaining_hours = None
    sla_hours = get_sla_hours(task.project, system_setting_value=sla_hours_setting)
    if task.due_at:
        sla_deadline = task.due_at + timedelta(seconds=paused_seconds)
    elif sla_hours:
        sla_deadline = task.created_at + timedelta(hours=sla_hours, seconds=paused_seconds)

    status = 'normal'
    level = 'green'
    thresholds = get_sla_thresholds(system_setting_value=sla_thresholds_setting)
    amber_limit = thresholds.get('amber', 6)
    red_limit = thresholds.get('red', 2)
    if sla_deadline:
        delta = sla_deadline - now
        remaining_hours = round(delta.total_seconds() / 3600, 1)
        if remaining_hours <= 0:
            status = 'overdue'
            level = 'red'
        elif remaining_hours <= red_limit:
            status = 'tight'
            level = 'red'
        elif remaining_hours <= amber_limit:
            status = 'tight'
            level = 'amber'
        else:
            level = 'green'
    else:
        level = 'grey'

    sort_value = {
        'red': 0,
        'amber': 1,
        'green': 2,
        'grey': 3,
    }.get(level, 3)
    return {
        'deadline': sla_deadline,
        'remaining_hours': remaining_hours,
        'status': status,
        'paused': bool(timer and timer.paused_at),
        'level': level,
        'sort': sort_value,
    }
