from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone

from .models import Task, DailyReport, SystemSetting


def _invalidate_stats_cache():
    # 清除绩效缓存，包含带筛选的前缀
    prefixes = ["performance_stats_v1", "performance_stats_v1_None_None"]
    for key in prefixes:
        cache.delete(key)
    if hasattr(cache, "delete_pattern"):
        try:
            cache.delete_pattern("performance_stats_v1_*")
        except Exception:
            pass
    today = timezone.localdate()
    for project_filter in ("", "None", None):
        for role_filter in ("", "None", None):
            cache.delete(f"stats_metrics_v1_{today}_{project_filter}_{role_filter}")


def _invalidate_sla_cache():
    # 清除SLA相关缓存
    cache.delete("sla_hours_setting")
    cache.delete("sla_thresholds_setting")


@receiver(post_save, sender=Task)
def clear_cache_on_task_change(sender, **kwargs):
    _invalidate_stats_cache()


@receiver(post_save, sender=DailyReport)
def clear_cache_on_report_change(sender, **kwargs):
    _invalidate_stats_cache()


@receiver(post_save, sender=SystemSetting)
def clear_cache_on_system_setting_change(sender, **kwargs):
    instance = kwargs.get('instance')
    if instance and instance.key in ['sla_hours', 'sla_thresholds']:
        _invalidate_sla_cache()


@receiver(post_delete, sender=Task)
def clear_cache_on_task_delete(sender, **kwargs):
    _invalidate_stats_cache()


@receiver(post_delete, sender=DailyReport)
def clear_cache_on_report_delete(sender, **kwargs):
    _invalidate_stats_cache()


@receiver(post_delete, sender=SystemSetting)
def clear_cache_on_system_setting_delete(sender, **kwargs):
    _invalidate_sla_cache()


@receiver(m2m_changed, sender=DailyReport.projects.through)
def clear_cache_on_report_project_link(sender, **kwargs):
    _invalidate_stats_cache()
