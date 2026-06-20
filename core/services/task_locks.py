import uuid
from contextlib import contextmanager

from django.core.cache import cache


@contextmanager
def task_lock(name, timeout=600):
    key = f"task-lock:{name}"
    token = uuid.uuid4().hex
    acquired = cache.add(key, token, timeout)
    try:
        yield acquired
    finally:
        if acquired and cache.get(key) == token:
            cache.delete(key)
