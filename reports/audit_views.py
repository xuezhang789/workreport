from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.utils import timezone

from audit.models import AuditLog
from core.utils import _admin_forbidden
from audit.utils import log_action

@login_required
def audit_logs(request):
    """
    System-wide audit logs view.
    Only for superusers (or admins with specific permission).
    """
    if not request.user.is_superuser:
        return _admin_forbidden(request)

    start_date = parse_date(request.GET.get('start_date') or '')
    end_date = parse_date(request.GET.get('end_date') or '')
    action = (request.GET.get('action') or '').strip()
    result = (request.GET.get('result') or '').strip()
    user_q = (request.GET.get('user') or '').strip()
    target_type = (request.GET.get('target_type') or '').strip()
    target_id = (request.GET.get('target_id') or '').strip()
    ip = (request.GET.get('ip') or '').strip()

    qs = AuditLog.objects.select_related('user').order_by('-created_at')

    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)
    if action:
        qs = qs.filter(action=action)
    if result:
        qs = qs.filter(result=result)
    if user_q:
        qs = qs.filter(Q(user__username__icontains=user_q) | Q(user__first_name__icontains=user_q) | Q(user__last_name__icontains=user_q))
    if target_type:
        qs = qs.filter(target_type__icontains=target_type)
    if target_id:
        qs = qs.filter(target_id=target_id)
    if ip:
        qs = qs.filter(ip__icontains=ip)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Log this access (meta-audit!)
    # 记录此次访问（元审计！）
    log_action(request, 'access', f"audit_logs page={page_obj.number}")

    context = {
        'logs': page_obj,
        'page_obj': page_obj,
        'start_date': start_date,
        'end_date': end_date,
        'action': action,
        'result': result,
        'user_q': user_q,
        'target_type': target_type,
        'target_id': target_id,
        'ip': ip,
        'action_choices': AuditLog.ACTION_CHOICES,
        'result_choices': AuditLog.RESULT_CHOICES,
    }
    return render(request, 'reports/audit_logs.html', context)


@login_required
def api_audit_logs(request):
    """
    API endpoint for fetching audit logs (e.g., for modal history view).
    Accessible by users for objects they can view? 
    Currently restricted to superusers or specific object checks.
    """
    # For now, let's keep it consistent with the view: superuser only.
    # If we want object-level history, we should check permissions on the object.
    # 目前，让我们与视图保持一致：仅限超级用户。
    # 如果我们需要对象级历史记录，我们应该检查对象的权限。
    
    target_type = request.GET.get('target_type')
    target_id = request.GET.get('target_id')
    
    if not (request.user.is_superuser):
         # Allow if checking history of something they own?
         # For now, strict.
         # 如果检查他们拥有的东西的历史记录，是否允许？
         # 目前，严格限制。
         return JsonResponse({'error': 'Permission denied'}, status=403)

    qs = AuditLog.objects.filter(target_type=target_type, target_id=target_id).order_by('-created_at')
    
    data = []
    for log in qs[:50]: # Limit to 50
        data.append({
            'date': timezone.localtime(log.created_at).strftime("%Y-%m-%d %H:%M:%S"),
            'user': log.user.get_full_name() or log.user.username if log.user else 'System',
            'action': log.get_action_display(),
            'summary': log.summary,
            'details': log.details,
        })
        
    return JsonResponse({'logs': data})
