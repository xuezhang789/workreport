from core.models import UserPreference


ALLOWED_PAGE_SIZES = (10, 20, 50, 100)
ALLOWED_UI_DENSITIES = ('comfortable', 'compact')
MAX_PREFERENCE_SECTION_BYTES = 4096
UI_SESSION_KEY = 'ui_preferences'
REQUEST_UI_CACHE_ATTR = '_workreport_ui_preferences'


def normalize_page_size(value, default=20):
    try:
        page_size = int(value)
    except (TypeError, ValueError):
        return default if default in ALLOWED_PAGE_SIZES else 20
    return page_size if page_size in ALLOWED_PAGE_SIZES else default


def normalize_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True
        if normalized in {'0', 'false', 'no', 'off'}:
            return False
        return default
    return bool(value)


def normalize_ui_preferences(value):
    raw = value if isinstance(value, dict) else {}
    page_size = normalize_page_size(raw.get('page_size'), UserPreference.DEFAULT_UI['page_size'])
    density = raw.get('density') if raw.get('density') in ALLOWED_UI_DENSITIES else UserPreference.DEFAULT_UI['density']
    return {
        'page_size': page_size,
        'density': density,
        'reduce_motion': normalize_bool(raw.get('reduce_motion'), UserPreference.DEFAULT_UI['reduce_motion']),
    }


def get_user_ui_preferences(user):
    if not getattr(user, 'is_authenticated', False):
        return dict(UserPreference.DEFAULT_UI)
    try:
        pref = user.preferences
    except UserPreference.DoesNotExist:
        return dict(UserPreference.DEFAULT_UI)
    return normalize_ui_preferences(pref.get_ui())


def remember_ui_preferences(session, value):
    ui = normalize_ui_preferences(value)
    session[UI_SESSION_KEY] = ui
    if hasattr(session, 'modified'):
        session.modified = True
    return ui


def get_request_ui_preferences(request):
    cached = getattr(request, REQUEST_UI_CACHE_ATTR, None)
    if cached is not None:
        return dict(cached)

    session = getattr(request, 'session', None)
    if session is not None:
        ui = normalize_ui_preferences(session.get(UI_SESSION_KEY))
    else:
        ui = dict(UserPreference.DEFAULT_UI)

    setattr(request, REQUEST_UI_CACHE_ATTR, ui)
    return dict(ui)


def _resolve_ui_preferences(subject):
    if hasattr(subject, 'session'):
        return get_request_ui_preferences(subject)
    return get_user_ui_preferences(subject)


def resolve_page_size(subject, params, key='per_page', default=20):
    ui = _resolve_ui_preferences(subject)
    preferred_default = normalize_page_size(ui.get('page_size'), default)
    if params.get(key) in (None, ''):
        return preferred_default
    return normalize_page_size(params.get(key), preferred_default)
