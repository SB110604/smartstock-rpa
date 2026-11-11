from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.health import full_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> JSONResponse:
    """DB, Redis, Celery worker and beat status. 503 only when the core (db/redis) is down."""
    data = full_health()
    return JSONResponse(data, status_code=503 if data["status"] == "error" else 200)


@router.get("/health/live")
def live() -> dict[str, Any]:
    return {"status": "ok"}
