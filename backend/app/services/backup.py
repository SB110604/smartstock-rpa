"""Database backups (spec 8.7): pg_dump custom-format archives in BACKUP_DIR, newest BACKUP_KEEP kept; admin restore."""

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import settings as env
from app.core.errors import AppError, NotFound, ValidationFailed
from app.core.timeutil import now

PREFIX = "smartstock_"


def folder() -> Path:
    p = Path(env.BACKUP_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _tool(name: str) -> str:
    """pg_dump / pg_restore from PATH, $PG_BIN, or a standard PostgreSQL 16 install location."""
    found = shutil.which(name)
    if found:
        return found
    for base in filter(None, [os.environ.get("PG_BIN"), "/usr/lib/postgresql/16/bin", r"C:\Program Files\PostgreSQL\16\bin"]):
        for cand in (Path(base) / name, Path(base) / f"{name}.exe"):
            if cand.exists():
                return str(cand)
    raise AppError(f"{name} is not installed on the server", code="backup_unavailable", status_code=503)


def _conn() -> tuple[list[str], dict[str, str]]:
    url = make_url(env.DATABASE_URL)
    args = ["-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres", "-d", url.database or ""]
    environ = {**os.environ, "PGPASSWORD": url.password or ""}
    return args, environ


def create() -> dict[str, Any]:
    args, environ = _conn()
    name = f"{PREFIX}{now():%Y%m%d_%H%M%S}.dump"
    target = folder() / name
    res = subprocess.run([_tool("pg_dump"), *args, "-Fc", "--no-owner", "-f", str(target)], env=environ,
                         capture_output=True, text=True, timeout=600, check=False)
    if res.returncode != 0:
        target.unlink(missing_ok=True)
        raise AppError(f"Backup failed: {res.stderr.strip()[:300]}", code="backup_failed", status_code=500)
    prune()
    return describe(target)


def describe(p: Path) -> dict[str, Any]:
    st = p.stat()
    return {"name": p.name, "size": st.st_size, "created_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}


def list_all() -> list[dict[str, Any]]:
    return [describe(p) for p in sorted(folder().glob(f"{PREFIX}*.dump"), reverse=True)]


def prune(keep: int | None = None) -> int:
    keep = keep or env.BACKUP_KEEP
    files = sorted(folder().glob(f"{PREFIX}*.dump"), reverse=True)
    for old in files[keep:]:
        old.unlink(missing_ok=True)
    return max(0, len(files) - keep)


def path(name: str) -> Path:
    if "/" in name or "\\" in name or not name.startswith(PREFIX) or not name.endswith(".dump"):
        raise ValidationFailed("Invalid backup name")
    p = folder() / name
    if not p.exists():
        raise NotFound("Backup not found")
    return p


def restore(name: str) -> dict[str, Any]:
    """Replace the current database contents with a backup (pg_restore --clean). Destructive — admin only."""
    p = path(name)
    args, environ = _conn()
    res = subprocess.run([_tool("pg_restore"), *args, "--clean", "--if-exists", "--no-owner", "--single-transaction", str(p)],
                         env=environ, capture_output=True, text=True, timeout=1800, check=False)
    if res.returncode != 0:
        raise AppError(f"Restore failed: {res.stderr.strip()[:300]}", code="restore_failed", status_code=500)
    return {"restored": name}
