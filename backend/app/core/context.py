"""Per-request context (client IP) so the service-layer audit helper needs no request object."""

from contextvars import ContextVar

from starlette.types import ASGIApp, Receive, Scope, Send

request_ip: ContextVar[str | None] = ContextVar("request_ip", default=None)


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        fwd = headers.get(b"x-forwarded-for", b"").decode().split(",")[0].strip()
        client = scope.get("client")
        token_ip = request_ip.set(fwd or (client[0] if client else None))
        try:
            await self.app(scope, receive, send)
        finally:
            request_ip.reset(token_ip)
