
import os
from django import template

register = template.Library()

@register.filter
def basename(value):
    """
    Returns the basename of the file path.
    Example: 'tasks/attachments/report.pdf' -> 'report.pdf'
    """
    if not value:
        return ''
    return os.path.basename(value)
