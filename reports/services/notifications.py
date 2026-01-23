from django.core.mail import send_mail
from django.conf import settings
from reports.models import Task

def send_weekly_digest(recipient: str, stats: dict):
    """发送周报邮件，汇总项目/角色完成率与连签情况。"""
    if not recipient:
        return False
    top_projects = sorted(stats.get('project_stats', []), key=lambda x: (-x['completion_rate'], x['overdue_rate']))[:5]
    top_roles = sorted(stats.get('role_stats', []), key=lambda x: (-x['completion_rate'], x['overdue_rate']))[:5]
    streaks = stats.get('role_streaks', [])
    overdue_top = Task.objects.filter(status='overdue').select_related('project', 'user').order_by('-due_at')[:5]

    lines = [
        "Weekly Performance Digest / 周度绩效简报",
        "",
        "Top Projects / 项目排名：",
    ]
    for p in top_projects:
        lines.append(f"- {p['project']}: 完成 {p['completion_rate']:.1f}%, 逾期 {p['overdue_rate']:.1f}%")
    lines.append("")
    lines.append("Top Roles / 角色维度：")
    for r in top_roles:
        lines.append(f"- {r['role_label']}: 完成 {r['completion_rate']:.1f}%, 逾期 {r['overdue_rate']:.1f}%")
    lines.append("")
    lines.append("Streaks / 连签：")
    for s in streaks:
        lines.append(f"- {s['role_label']}: Avg 平均 {s['avg_streak']} 天, Max 最高 {s['max_streak']} 天")

    if overdue_top:
        lines.append("")
        lines.append("Overdue Tasks / 逾期任务 Top5：")
        for t in overdue_top:
            lines.append(f"- {t.title} [{t.project.name if t.project else 'N/A'}] by {t.user.get_full_name() or t.user.username}")

    send_mail(
        subject="Weekly Performance Digest / 周度绩效简报",
        message="\n".join(lines),
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
        recipient_list=[recipient],
        fail_silently=True,
    )
    return True
