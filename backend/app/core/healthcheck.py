"""Container healthcheck: `python -m app.core.healthcheck api|worker|beat` exits 0 when healthy."""

import socket
import sys
import urllib.request

from app.core import health


def main(target: str) -> int:
    if target == "api":
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/live", timeout=3) as r:
                return 0 if r.status == 200 else 1
        except OSError:
            return 1
    if target == "worker":
        from app.tasks.celery_app import celery_app

        name = f"worker@{socket.gethostname()}"
        replies = celery_app.control.inspect(destination=[name], timeout=3.0).ping() or {}
        return 0 if replies else 1
    if target == "beat":
        return 0 if health.check_beat()["status"] == "ok" else 1
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "api"))
