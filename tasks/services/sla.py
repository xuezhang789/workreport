from django.utils import timezone
from django.conf import settings
from tasks.models import TaskSlaTimer, Task
from core.models import SystemSetting
from core.constants import TaskStatus
import json
from datetime import timedelta

DEFAULT_SLA_HOURS = 48
DEFAULT_THRESHOLDS = {'amber': 4, 'red': 0}

def get_sla_hours(system_setting_value=None):
    """
    获取配置的 SLA 小时数，如果未提供则检查缓存或数据库。
    """
    if system_setting_value is not None:
        return system_setting_value
    
    # 暂时不使用缓存进行简单获取，或者依赖调用者传递值
    # 在生产环境中，建议缓存此值
    try:
        setting = SystemSetting.objects.get(key='sla_hours')
        return int(setting.value)
    except (SystemSetting.DoesNotExist, ValueError):
        return DEFAULT_SLA_HOURS

def get_sla_thresholds(system_setting_value=None):
    """
    获取配置的 SLA 阈值 (橙色/红色 小时数)。
    """
    if system_setting_value:
        try:
            return json.loads(system_setting_value)
        except json.JSONDecodeError:
            pass
            
    try:
        setting = SystemSetting.objects.get(key='sla_thresholds')
        return json.loads(setting.value)
    except (SystemSetting.DoesNotExist, json.JSONDecodeError):
        return DEFAULT_THRESHOLDS

def _ensure_sla_timer(task):
    """
    确保任务存在 TaskSlaTimer。
    """
    timer, created = TaskSlaTimer.objects.get_or_create(task=task)
    return timer

from django.core.exceptions import ObjectDoesNotExist

def _get_sla_timer_readonly(task):
    """
    获取计时器而不创建它 (用于列表)。
    """
    # 优化：直接访问属性。如果已通过 select_related 获取，它会使用缓存。
    # 如果不存在（无论是缓存中不存在还是数据库中不存在），会抛出异常，此时返回 None。
    # 避免了 hasattr 返回 False 后进行的额外数据库查询。
    try:
        return task.sla_timer
    except ObjectDoesNotExist:
        return None

def calculate_sla_info(task, as_of=None, sla_hours_setting=None, sla_thresholds_setting=None):
    """
    计算任务的详细 SLA 状态。
    """
    if as_of is None:
        as_of = timezone.now()
        
    # 确定 SLA 小时数
    # 优先级: 1. 项目设置 2. 系统设置 3. 默认
    if task.project and task.project.sla_hours:
        sla_hours = task.project.sla_hours
    else:
        sla_hours = get_sla_hours(sla_hours_setting)

    thresholds = sla_thresholds_setting or get_sla_thresholds()
    
    # 基本截止日期逻辑
    if not task.due_at:
        # 如果没有截止日期，也许从 created_at + SLA 计算？
        # 目前假设 due_at 是事实来源。
        # 如果 due_at 为 None，我们可以将其视为无 SLA 或使用默认窗口
        effective_due = task.created_at + timedelta(hours=sla_hours)
    else:
        effective_due = task.due_at

    # 计时器逻辑 (暂停)
    timer = _get_sla_timer_readonly(task)
    paused_seconds = 0
    is_paused = False
    
    if timer:
        paused_seconds = timer.total_paused_seconds
        if timer.paused_at:
            is_paused = True
            # 如果仍在暂停，添加当前暂停持续时间
            current_pause = (as_of - timer.paused_at).total_seconds()
            paused_seconds += int(current_pause)
            
    # 通过添加暂停时间调整有效截止日期
    # 如果我暂停了 1 小时，我的截止日期推迟 1 小时
    adjusted_due = effective_due + timedelta(seconds=paused_seconds)
    
    # 剩余时间
    remaining_delta = adjusted_due - as_of
    remaining_hours = remaining_delta.total_seconds() / 3600
    
    status = 'normal'
    level = 'green'
    sort_order = 3
    
    if task.status in (TaskStatus.DONE, TaskStatus.CLOSED):
        # 如果已完成，检查是否按时完成
        # 我们比较 completed_at 和 adjusted_due
        done_at = task.completed_at or as_of # 回退
        if done_at <= adjusted_due:
             status = 'on_time'
             level = 'success' # 或蓝色
        else:
             status = 'completed_late'
             level = 'red'
        remaining_hours = 0 # 对于已完成无意义
        sort_order = 4
        
    elif is_paused:
        status = 'paused'
        level = 'grey'
        sort_order = 2
        
    elif remaining_hours < thresholds.get('red', 0):
        status = 'overdue'
        level = 'red'
        sort_order = 0
    elif remaining_hours < thresholds.get('amber', 4):
        status = 'tight'
        level = 'amber'
        sort_order = 1
        
    return {
        'status': status,
        'level': level,
        'remaining_hours': round(remaining_hours, 1),
        'adjusted_due': adjusted_due,
        'is_paused': is_paused,
        'sort': sort_order
    }
