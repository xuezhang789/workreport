from django.core.cache import cache


REGISTRY_PREFIX = 'cache_key_registry'
REGISTRY_TIMEOUT = 24 * 60 * 60


def _registry_key(group):
    return f'{REGISTRY_PREFIX}:{group}'


def cache_set_tracked(key, value, timeout, *groups):
    cache.set(key, value, timeout)
    for group in groups:
        registry_key = _registry_key(group)
        keys = list(cache.get(registry_key, ()))
        if key not in keys:
            keys.append(key)
            cache.set(registry_key, keys, REGISTRY_TIMEOUT)


def invalidate_cache_group(group):
    registry_key = _registry_key(group)
    keys = cache.get(registry_key, ())
    if keys:
        cache.delete_many(keys)
    cache.delete(registry_key)
