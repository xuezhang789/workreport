from django.core.cache import cache
from django.db import transaction


VERSION_KEY_PREFIX = 'permission_cache_version'


def get_permission_cache_version(user_id):
    key = f'{VERSION_KEY_PREFIX}:{user_id}'
    version = cache.get(key)
    if version is None:
        cache.add(key, 1, timeout=None)
        version = cache.get(key, 1)
    return int(version)


def _bump_permission_cache_version(user_id):
    key = f'{VERSION_KEY_PREFIX}:{user_id}'
    if cache.add(key, 2, timeout=None):
        return 2
    try:
        return cache.incr(key)
    except (ValueError, TypeError):
        version = get_permission_cache_version(user_id) + 1
        cache.set(key, version, timeout=None)
        return version


def invalidate_user_permission_cache(user_id):
    version = _bump_permission_cache_version(user_id)
    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(lambda: _bump_permission_cache_version(user_id))
    return version


def user_permission_cache_key(prefix, user_id, *parts):
    version = get_permission_cache_version(user_id)
    suffix = ':'.join(str(part) for part in parts)
    return f'{prefix}:user:{user_id}:v:{version}' + (f':{suffix}' if suffix else '')
