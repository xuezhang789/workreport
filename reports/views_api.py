from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from core.models import ReportJob
from reports.services.stats import generate_gantt_data, generate_burndown_data, generate_cfd_data
import threading
import json

@login_required
@require_http_methods(["GET"])
def api_advanced_gantt(request):
    project_id = request.GET.get('project_id')
    page = int(request.GET.get('page', 1))
    limit = int(request.GET.get('limit', 50))
    
    if project_id and project_id.isdigit():
        project_id = int(project_id)
    else:
        project_id = None
        
    data = generate_gantt_data(project_id, page, limit)
    return JsonResponse(data)

def run_report_job(job_id):
    try:
        job = ReportJob.objects.get(id=job_id)
        job.status = 'running'
        job.save()
        
        project_id = job.params.get('project_id')
        
        if job.report_type == 'burndown':
            data = generate_burndown_data(project_id)
        elif job.report_type == 'cfd':
            data = generate_cfd_data(project_id)
        else:
            raise ValueError("Unknown report type")
            
        job.result = data
        job.status = 'done'
        job.save()
    except Exception as e:
        # Re-fetch to avoid race conditions if possible
        try:
            job = ReportJob.objects.get(id=job_id)
            job.status = 'failed'
            job.error_message = str(e)
            job.save()
        except:
            pass

@login_required
@require_http_methods(["POST"])
def api_start_report_job(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
        
    report_type = data.get('report_type')
    project_id = data.get('project_id')
    
    if project_id:
        project_id = int(project_id)
        
    # Check cache first
    cache_key = f"report_{report_type}_{project_id}"
    cached_data = cache.get(cache_key)
    if cached_data:
        # Return immediate success with data
        # We don't necessarily need to create a job if it's cached, 
        # but to keep frontend logic consistent (poll -> done), we can return a fake job ID 
        # or just return status='done' and result immediately.
        # Let's return status done and result.
        return JsonResponse({'status': 'done', 'result': cached_data, 'cached': True})

    job = ReportJob.objects.create(
        user=request.user,
        report_type=report_type,
        params={'project_id': project_id},
        status='pending'
    )
    
    # Run in thread (Simulating Async Worker)
    t = threading.Thread(target=run_report_job, args=(job.id,), daemon=True)
    t.start()
    
    return JsonResponse({'job_id': job.id, 'status': 'pending'})

@login_required
@require_http_methods(["GET"])
def api_check_report_job(request, job_id):
    try:
        job = ReportJob.objects.get(id=job_id, user=request.user)
    except ReportJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found'}, status=404)
        
    if job.status == 'done':
        # Cache result for future (5 mins)
        project_id = job.params.get('project_id')
        cache_key = f"report_{job.report_type}_{project_id}"
        cache.set(cache_key, job.result, 300)
        
    return JsonResponse({
        'id': job.id,
        'status': job.status,
        'result': job.result,
        'error': job.error_message
    })
