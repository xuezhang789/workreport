from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.services.search_index import global_search as indexed_global_search
from audit.utils import log_action

@login_required
def global_search(request):
    q = (request.GET.get('q') or '').strip()
    scope = request.GET.get('scope', 'all')
    
    results = {
        'projects': [],
        'tasks': [],
        'reports': [],
        'users': [],
    }
    
    if q:
        results, _hits = indexed_global_search(request.user, q, scope=scope, limit_per_type=10)
        log_action(request, 'search', f"global_search q={q} scope={scope}")

    context = {
        'q': q,
        'scope': scope,
        'results': results,
        'total_hits': len(results['projects']) + len(results['tasks']) + len(results['reports']) + len(results['users'])
    }
    return render(request, 'reports/global_search.html', context)
