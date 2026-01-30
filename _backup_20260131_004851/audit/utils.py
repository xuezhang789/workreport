import time
from audit.models import AuditLog

def log_action(request, action: str, extra: str = "", data=None):
    ip = request.META.get('REMOTE_ADDR')
    # Handle Proxy
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
        
    ua = request.META.get('HTTP_USER_AGENT', '')[:512]
    elapsed_ms = getattr(request, '_elapsed_ms', None)
    if elapsed_ms is None and hasattr(request, '_elapsed_start'):
        elapsed_ms = int((time.monotonic() - request._elapsed_start) * 1000)
    
    # Try to determine operator name if user is not logged in but we have a username in data
    user = request.user if request.user.is_authenticated else None
    operator_name = user.get_full_name() or user.username if user else 'System/Anonymous'
    
    details = {
        'context': {
            'path': request.path[:255],
            'method': request.method,
            'ua': ua,
            'elapsed_ms': elapsed_ms
        },
        'data': data or {}
    }

    # Avoid logging redundant update actions if data is empty (likely covered by signals)
    if action == 'update' and not data and not extra:
         # Optionally skip, but 'extra' often has summary string.
         pass
         
    # Fix for duplication: log_action should create 'AccessLog' type, but previous code might be creating valid Task logs?
    # Actually, signals create logs with target_type='Task'.
    # log_action creates logs with target_type='AccessLog'.
    # So duplication in History View comes from View querying target_type='Task'.
    # Wait, the failure shows TWO logs with 'diff'.
    # Log: update - Details: {'diff': {'status': {'verbose_name': '状态', 'old': '待处理 / To Do', 'new': '进行中 / In Progress'}}}
    # Log: update - Details: {'diff': {'status': {'old': 'todo', 'new': 'in_progress'}}}
    
    # One has verbose_name, one doesn't.
    # The one with verbose_name looks like AuditService._calculate_diff?
    # The other one looks like _add_history's replacement?
    # I removed _add_history call in views.py.
    # Let's check if signals.py is doing something twice or if there's another hook.
    
    AuditLog.objects.create(
        user=user,
        operator_name=operator_name,
        action=action,
        ip=ip,
        summary=extra[:2000],
        details=details,
        target_type='AccessLog', # Mark manual logs distinct from Data Changes
        target_id='0',
        target_label='System Access',
        result='success'
    )
