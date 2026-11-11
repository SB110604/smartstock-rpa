import contextlib
import threading
import time

import redis

from app.core.config import settings
from app.core.errors import RateLimited

_local: dict[str, list[float]] = {}
_lock = threading.Lock()


def _redis_hit(key: str, window: int) -> int:
    r = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, window, nx=True)
    count, _ = pipe.execute()
    return int(count)


def _local_hit(key: str, window: int) -> int:
    now = time.time()
    with _lock:
        hits = [t for t in _local.get(key, []) if now - t < window]
        hits.append(now)
        _local[key] = hits
        return len(hits)


def hit(key: str, limit: int, window: int = 60) -> None:
    """Fixed-window limiter backed by Redis; falls back to process memory if Redis is unreachable."""
    full = f"smartstock:rl:{key}"
    try:
        count = _redis_hit(full, window)
    except redis.RedisError:
        count = _local_hit(full, window)
    if count > limit:
        raise RateLimited("Too many attempts. Please wait a minute and try again.")


def reset(key: str) -> None:
    full = f"smartstock:rl:{key}"
    with _lock:
        _local.pop(full, None)
    with contextlib.suppress(redis.RedisError):
        redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5).delete(full)
