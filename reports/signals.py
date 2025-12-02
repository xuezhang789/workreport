from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.core.cache import cache
from django.utils import timezone

from .models import Task, DailyReport


def _invalidate_stats_cache():
    cache.delete("performance_stats_v1")
    today = timezone.localdate()
    for project_filter in ("", "None", None):
        for role_filter in ("", "None", None):
            cache.delete(f"stats_metrics_v1_{today}_{project_filter}_{role_filter}")


@receiver(post_save, sender=Task)
def clear_cache_on_task_change(sender, **kwargs):
    _invalidate_stats_cache()


@receiver(post_save, sender=DailyReport)
def clear_cache_on_report_change(sender, **kwargs):
    _invalidate_stats_cache()


@receiver(post_delete, sender=Task)
def clear_cache_on_task_delete(sender, **kwargs):
    _invalidate_stats_cache()


@receiver(post_delete, sender=DailyReport)
def clear_cache_on_report_delete(sender, **kwargs):
    _invalidate_stats_cache()
