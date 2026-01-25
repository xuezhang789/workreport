from django.utils import timezone
from django.conf import settings
from ..models import TaskSlaTimer, SystemSetting, Task
import json
from datetime import timedelta

DEFAULT_SLA_HOURS = 48
DEFAULT_THRESHOLDS = {'amber': 4, 'red': 0}

def get_sla_hours(system_setting_value=None):
    """
    Get configured SLA hours, checking cache or DB if not provided.
    """
    if system_setting_value is not None:
        return system_setting_value
    
    # Simple fetch without cache for now, or rely on caller to pass value
    # In production, cache this
    try:
        setting = SystemSetting.objects.get(key='sla_hours')
        return int(setting.value)
    except (SystemSetting.DoesNotExist, ValueError):
        return DEFAULT_SLA_HOURS

def get_sla_thresholds(system_setting_value=None):
    """
    Get configured SLA thresholds (orange/red hours).
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
    Ensure a TaskSlaTimer exists for the task.
    """
    timer, created = TaskSlaTimer.objects.get_or_create(task=task)
    return timer

def _get_sla_timer_readonly(task):
    """
    Get timer without creating one (for lists).
    """
    if hasattr(task, 'slatimer'):
        return task.slatimer
    return TaskSlaTimer.objects.filter(task=task).first()

def calculate_sla_info(task, as_of=None, sla_hours_setting=None, sla_thresholds_setting=None):
    """
    Calculate detailed SLA status for a task.
    """
    if as_of is None:
        as_of = timezone.now()
        
    sla_hours = get_sla_hours(sla_hours_setting)
    thresholds = sla_thresholds_setting or get_sla_thresholds()
    
    # Basic Due Date Logic
    if not task.due_at:
        # If no due date, maybe calculate from created_at + SLA?
        # Assuming due_at is the source of truth for now.
        # If due_at is None, we can treat it as no SLA or use default window
        effective_due = task.created_at + timedelta(hours=sla_hours)
    else:
        effective_due = task.due_at

    # Timer logic (pauses)
    timer = _get_sla_timer_readonly(task)
    paused_seconds = 0
    is_paused = False
    
    if timer:
        paused_seconds = timer.total_paused_seconds
        if timer.paused_at:
            is_paused = True
            # Add current pause duration if still paused
            current_pause = (as_of - timer.paused_at).total_seconds()
            paused_seconds += int(current_pause)
            
    # Adjust effective due date by adding paused time
    # If I paused for 1 hour, my due date is pushed back by 1 hour
    adjusted_due = effective_due + timedelta(seconds=paused_seconds)
    
    # Remaining time
    remaining_delta = adjusted_due - as_of
    remaining_hours = remaining_delta.total_seconds() / 3600
    
    status = 'normal'
    level = 'green'
    sort_order = 3
    
    if task.status == 'completed':
        # If completed, check if it was done on time
        # We compare completed_at with adjusted_due
        done_at = task.completed_at or as_of # fallback
        if done_at <= adjusted_due:
             status = 'on_time'
             level = 'success' # or blue
        else:
             status = 'overdue'
             level = 'red'
        remaining_hours = 0 # Meaningless for completed
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
