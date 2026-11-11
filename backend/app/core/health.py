import time
from typing import Any

import redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine

HEARTBEAT_KEY = "smartstock:beat:last"


def check_db() -> dict[str, Any]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:  # health must report, not raise
        return {"status": "error", "error": type(exc).__name__}


def _redis() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)


def check_redis() -> dict[str, Any]:
    try:
        _redis().ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}


def check_worker() -> dict[str, Any]:
    try:
        from app.tasks.celery_app import celery_app

        replies = celery_app.control.inspect(timeout=1.0).ping() or {}
        if replies:
            return {"status": "ok", "workers": sorted(replies)}
        return {"status": "down", "workers": []}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}


def check_beat() -> dict[str, Any]:
    try:
        raw = _redis().get(HEARTBEAT_KEY)
        if raw is None:
            return {"status": "down"}
        age = time.time() - float(raw)
        return {"status": "ok" if age < 180 else "stale", "last_seconds_ago": round(age)}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}


def full_health() -> dict[str, Any]:
    components = {"db": check_db(), "redis": check_redis(), "worker": check_worker(), "beat": check_beat()}
    core_ok = components["db"]["status"] == "ok" and components["redis"]["status"] == "ok"
    all_ok = all(c["status"] == "ok" for c in components.values())
    return {"status": "ok" if all_ok else ("degraded" if core_ok else "error"), **components}
