import mimetypes
import os

from django.http import FileResponse, Http404
from django.utils.http import content_disposition_header


def protected_file_response(field_file, *, filename=None, as_attachment=False):
    """Stream a FileField through an authorized view without exposing storage URLs."""
    if not field_file or not field_file.name:
        raise Http404("File not found")

    download_name = os.path.basename(filename or field_file.name)
    content_type, _ = mimetypes.guess_type(download_name)
    try:
        file_handle = field_file.open('rb')
    except (FileNotFoundError, OSError, ValueError):
        raise Http404("File not found")

    response = FileResponse(
        file_handle,
        content_type=content_type or 'application/octet-stream',
    )
    response.headers['Content-Disposition'] = content_disposition_header(
        as_attachment,
        download_name,
    )
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
