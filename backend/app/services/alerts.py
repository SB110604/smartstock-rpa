"""Alerts (spec section 5): raised by agents and workflows, de-duplicated by fingerprint while open."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import now
from app.models.ai import Alert
from app.models.core import Role, User
from app.services import audit, notify

TYPES = ("low_stock", "out_of_stock", "expiry_warning", "expiry_critical", "expired", "dead_stock", "anomaly",
         "late_delivery", "approval_pending", "three_way_mismatch", "forecast_drift", "suggestion_rejected", "info")

# who hears about which alert type (in-app + configured channels)
AUDIENCE: dict[str, tuple[str, ...]] = {
    "low_stock": (Role.MANAGER,), "out_of_stock": (Role.MANAGER, Role.STAFF), "expiry_warning": (Role.MANAGER,),
    "expiry_critical": (Role.MANAGER, Role.STAFF), "expired": (Role.MANAGER, Role.STAFF),
    "dead_stock": (Role.MANAGER,), "anomaly": (Role.ADMIN,), "late_delivery": (Role.MANAGER,),
    "approval_pending": (Role.MANAGER,), "three_way_mismatch": (Role.MANAGER,), "forecast_drift": (Role.ADMIN,),
    "suggestion_rejected": (Role.MANAGER,), "info": (Role.MANAGER,),
}
LINKS = {"three_way_mismatch": "/orders/{ref_id}", "late_delivery": "/orders/{ref_id}", "approval_pending": "/approvals",
         "anomaly": "/insights?tab=anomalies", "forecast_drift": "/insights?tab=performance"}


def raise_alert(
    db: Session,
    type: str,
    message: str,
    *,
    severity: str = "warning",
    product_id: int | None = None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    data: dict[str, Any] | None = None,
    key: str | None = None,
    send: bool = True,
) -> tuple[Alert, bool]:
    """Create an alert unless an open one with the same fingerprint exists (then refresh it).
    Returns (alert, created)."""
    if type not in TYPES:
        raise ValueError(f"unknown alert type {type}")
    fingerprint = key or f"{type}:{product_id or ''}:{ref_type or ''}:{ref_id or ''}"
    existing = db.scalar(select(Alert).where(Alert.fingerprint == fingerprint, Alert.status.in_(("open", "acknowledged"))))
    if existing:
        existing.message, existing.severity, existing.data_json = message, severity, data
        return existing, False
    alert = Alert(type=type, severity=severity, product_id=product_id, ref_type=ref_type, ref_id=ref_id, message=message,
                  data_json=data, fingerprint=fingerprint)
    db.add(alert)
    db.flush()
    if send:
        link = LINKS.get(type, "/alerts").format(ref_id=ref_id or "")
        if type in ("low_stock", "out_of_stock", "expired", "expiry_critical", "expiry_warning", "dead_stock") and product_id:
            link = f"/products/{product_id}"
        channels = {"in_app", "email", "telegram"} if severity == "critical" else {"in_app"}
        notify.notify_roles(db, AUDIENCE.get(type, (Role.MANAGER,)), f"{type.replace('_', ' ').title()}", message,
                            link=link, alert_id=alert.id, channels=channels)
    return alert, True


def resolve_by_key(db: Session, key: str, note: str = "auto-resolved") -> int:
    rows = list(db.scalars(select(Alert).where(Alert.fingerprint == key, Alert.status.in_(("open", "acknowledged")))))
    for a in rows:
        a.status, a.resolution, a.resolved_at = "resolved", note, now()
    return len(rows)


def get(db: Session, alert_id: int) -> Alert:
    a = db.get(Alert, alert_id)
    if not a:
        raise NotFound("Alert not found")
    return a


def acknowledge(db: Session, alert: Alert, user: User) -> Alert:
    if alert.status == "resolved":
        raise ValidationFailed("Alert is already resolved")
    before = audit.snapshot(alert)
    alert.status = "acknowledged"
    audit.record(db, user, "update", "alerts", alert.id, before, audit.snapshot(alert))
    db.commit()
    return alert


def resolve(db: Session, alert: Alert, user: User, resolution: str | None) -> Alert:
    before = audit.snapshot(alert)
    alert.status, alert.resolution, alert.resolved_by, alert.resolved_at = "resolved", resolution, user.id, now()
    audit.record(db, user, "update", "alerts", alert.id, before, audit.snapshot(alert))
    db.commit()
    return alert
