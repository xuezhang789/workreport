
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from core.services.upload_service import UploadService
import json

from core.utils import UPLOAD_MAX_SIZE, UPLOAD_ALLOWED_EXTENSIONS, AVATAR_MAX_SIZE, AVATAR_ALLOWED_EXTENSIONS

@login_required
@require_POST
def upload_init(request):
    try:
        data = json.loads(request.body)
        filename = data.get('filename')
        size = data.get('size')
        upload_type = data.get('type', 'default') # 'project', 'task', 'avatar'
        
        if not filename or not size:
            return JsonResponse({'status': 'error', 'message': 'Missing filename or size'}, status=400)
            
        # Determine constraints based on type
        max_size = UPLOAD_MAX_SIZE
        allowed_extensions = UPLOAD_ALLOWED_EXTENSIONS
        
        if upload_type == 'avatar':
            max_size = AVATAR_MAX_SIZE
            allowed_extensions = AVATAR_ALLOWED_EXTENSIONS
        elif upload_type == 'project':
             max_size = 10 * 1024 * 1024 # Explicit 10MB
        elif upload_type == 'task':
             max_size = 50 * 1024 * 1024 # Allow larger files for tasks
            
        upload, error = UploadService.init_chunked_upload(request.user, filename, int(size), max_size=max_size, allowed_extensions=allowed_extensions)
        if error:
            return JsonResponse({'status': 'error', 'message': error}, status=400)
            
        return JsonResponse({
            'status': 'success', 
            'upload_id': str(upload.id),
            'uploaded_size': upload.uploaded_size
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def upload_chunk(request):
    upload_id = request.POST.get('upload_id')
    chunk_index = request.POST.get('chunk_index')
    offset = request.POST.get('offset')
    file = request.FILES.get('file')
    
    if not upload_id or not file:
        return JsonResponse({'status': 'error', 'message': 'Missing data'}, status=400)
        
    try:
        offset = int(offset) if offset else None
        success, error = UploadService.process_chunk(upload_id, chunk_index, file, offset)
        if not success:
            return JsonResponse({'status': 'error', 'message': error}, status=400)
            
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def upload_complete(request):
    """
    Check if upload is complete. 
    Note: This doesn't move the file to final destination yet.
    It just confirms readiness. 
    The client will then send the upload_id to the specific business view.
    """
    try:
        data = json.loads(request.body)
        upload_id = data.get('upload_id')
        
        # Verify
        from core.models import ChunkedUpload
        upload = ChunkedUpload.objects.get(id=upload_id, user=request.user)
        if upload.uploaded_size != upload.file_size:
             return JsonResponse({'status': 'error', 'message': 'Incomplete upload'}, status=400)
             
        upload.status = 'complete'
        upload.save()
        
        return JsonResponse({'status': 'success', 'upload_id': upload_id})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@login_required
@require_POST
def upload_avatar_complete(request):
    """
    Finalize avatar upload and update user profile.
    """
    try:
        data = json.loads(request.body)
        upload_id = data.get('upload_id')
        
        from core.models import ChunkedUpload
        upload = ChunkedUpload.objects.get(id=upload_id, user=request.user)
        
        # Finalize
        content_file, error = UploadService.complete_chunked_upload(upload_id)
        if error:
            return JsonResponse({'status': 'error', 'message': error}, status=400)
            
        # Save to storage
        # We use a specific path for avatars
        import os
        from django.core.files.storage import default_storage
        from django.conf import settings
        
        ext = os.path.splitext(upload.filename)[1]
        filename = f"avatars/user_{request.user.id}_{int(os.path.getmtime(upload.temp_path) if os.path.exists(upload.temp_path) else 0)}{ext}"
        # Use simple timestamp or uuid for cache busting
        import time
        filename = f"avatars/user_{request.user.id}_{int(time.time())}{ext}"
        
        path = default_storage.save(filename, content_file)
        url = default_storage.url(path)
        
        # Update UserPreference
        from core.models import UserPreference
        prefs, created = UserPreference.objects.get_or_create(user=request.user)
        
        if 'profile' not in prefs.data:
            prefs.data['profile'] = {}
        
        prefs.data['profile']['avatar_data_url'] = url
        prefs.save()
        
        return JsonResponse({'status': 'success', 'url': url})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
