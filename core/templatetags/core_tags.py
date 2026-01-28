from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """
    Return encoded URL parameters that are the same as the current
    request's parameters, only with the specified parameters added or changed.

    It also removes any empty parameters to keep things clean,
    unless an explicit empty string is passed as a new value.
    """
    query = context['request'].GET.dict()
    query.update(kwargs)
    
    # Optional: Remove 'page' if it's 1? No, let's keep it simple.
    # Optional: Remove empty keys?
    # for key in list(query.keys()):
    #     if not query[key]:
    #         del query[key]
            
    from urllib.parse import urlencode
    return urlencode(query)
