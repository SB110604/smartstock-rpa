"""Audit log helper — every create/update/delete in the service layer goes through `record`."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.context import request_ip
from app.models.core import AuditLog, User

_SECRET_FIELDS = {"password_hash", "totp_secret", "key_hash", "token_hash"}


def _json(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def snapshot(obj: Any) -> dict[str, Any]:
    """Column values of a model instance as JSON-safe data (secrets masked)."""
    mapper = inspect(obj).mapper
    out: dict[str, Any] = {}
    for col in mapper.column_attrs:
        key = col.key
        if key in ("created_at", "updated_at"):
            continue
        out[key] = "***" if key in _SECRET_FIELDS and getattr(obj, key) else _json(getattr(obj, key))
    return out


def diff(
    before: dict[str, Any] | None, after: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Keep only changed keys for updates so the audit diff view stays readable."""
    if before is None or after is None:
        return before, after
    keys = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return {k: before.get(k) for k in keys}, {k: after.get(k) for k in keys}


def record(
    db: Session,
    user: User | int | None,
    action: str,
    entity: str,
    entity_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    if action == "update":
        before, after = diff(before, after)
    uid = user.id if isinstance(user, User) else user
    log = AuditLog(
        user_id=uid,
        action=action,
        entity=entity,
        entity_id=None if entity_id is None else str(entity_id),
        before_json=before,
        after_json=after,
        ip=request_ip.get(),
    )
    db.add(log)
    return log


def created(db: Session, user: User | int | None, obj: Any, entity: str | None = None) -> None:
    db.flush()
    record(db, user, "create", entity or obj.__tablename__, obj.id, None, snapshot(obj))


def deleted(db: Session, user: User | int | None, obj: Any, entity: str | None = None) -> None:
    record(db, user, "delete", entity or obj.__tablename__, getattr(obj, "id", None), snapshot(obj), None)


def apply_update(
    db: Session, user: User | int | None, obj: Any, changes: dict[str, Any], entity: str | None = None
) -> Any:
    """Set attributes from `changes` and write an audit row with the before/after diff."""
    before = snapshot(obj)
    for k, v in changes.items():
        setattr(obj, k, v)
    db.flush()
    record(db, user, "update", entity or obj.__tablename__, getattr(obj, "id", None), before, snapshot(obj))
    return obj
