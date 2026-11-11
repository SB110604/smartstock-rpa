from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.context import RequestContextMiddleware
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)
    if settings.APP_ENV == "production" and settings.SECRET_KEY in ("dev-secret-change-me", "change-me-to-a-long-random-string"):
        raise RuntimeError("Set a strong SECRET_KEY environment variable before running in production")
    app = FastAPI(
        title="SmartStock RPA API",
        version="1.0.0",
        description="AI-driven Intelligent RPA for adaptive business workflow optimization.",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)
    app.include_router(api_router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response

    return app


app = create_app()
