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
         pass
         
    # Fix for duplication: 
    # Signals create logs with target_type='Task'/'Project' and detailed diffs.
    # Manual log_action creates logs with target_type='AccessLog' (or generic) and context.
    # To prevent duplication in History views (which query by Task/Project), 
    # we ensure manual logs use a distinct target_type unless explicitly overriding.
    
    AuditLog.objects.create(
        user=user,
        operator_name=operator_name,
        action=action,
        ip=ip,
        summary=extra[:2000],
        details=details,
        target_type='AccessLog', # Always use AccessLog for manual/view actions to distinguish from Data Changes
        target_id='0',
        target_label='System Access',
        result='success'
    )
