"""Business settings stored as key/value JSON rows, with defaults for every key (spec section 5)."""

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.models.core import Setting, User
from app.services import audit

DEFAULTS: dict[str, Any] = {
    "business": {
        "name": "SmartStock Store",
        "address": "",
        "city": "",
        "state": "Maharashtra",
        "gstin": "",
        "phone": "",
        "email": "",
    },
    "ordering_cost_S": 500.0,
    "holding_cost_pct": 20.0,
    "service_level": 0.95,
    "review_period_days": 7,
    "supplier_weights": {"price": 0.35, "ontime": 0.30, "lead": 0.20, "quality": 0.15},
    "expiry_thresholds": {"critical": 7, "warning": 30},
    "dead_stock_days": 60,
    "approval_sla_hours": 24,
    "match_tolerance": {"qty_pct": 0.0, "price_pct": 2.0},
    "notification_channels": {"in_app": True, "email": True, "telegram": False},
    "po_terms": (
        "1. Goods must match the ordered specification and be delivered before the expected date.\n"
        "2. Perishable goods must have at least 70% of shelf life remaining on delivery.\n"
        "3. Please quote the PO number on your invoice and delivery challan.\n"
        "4. Payment as per agreed credit terms after receipt and 3-way match."
    ),
    "markdown": {"critical_pct": 30, "warning_pct": 12},
}

_NUMERIC_KEYS = {
    "ordering_cost_S",
    "holding_cost_pct",
    "service_level",
    "review_period_days",
    "dead_stock_days",
    "approval_sla_hours",
}


def get_all(db: Session) -> dict[str, Any]:
    data = copy.deepcopy(DEFAULTS)
    for row in db.scalars(select(Setting)):
        if isinstance(data.get(row.key), dict) and isinstance(row.value, dict):
            data[row.key] = {**data[row.key], **row.value}
        else:
            data[row.key] = row.value
    return data


def get(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    default = copy.deepcopy(DEFAULTS.get(key))
    if row is None:
        return default
    if isinstance(default, dict) and isinstance(row.value, dict):
        return {**default, **row.value}
    return row.value


def _validate(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise ValidationFailed(f"Unknown setting '{key}'")
    if key in _NUMERIC_KEYS:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValidationFailed(f"{key} must be a number")
        if value < 0:
            raise ValidationFailed(f"{key} cannot be negative")
        if key == "service_level" and not 0.5 <= value < 1:
            raise ValidationFailed("service_level must be between 0.5 and 0.999")
        if key in ("review_period_days", "dead_stock_days"):
            value = int(value)
    if key == "supplier_weights":
        total = sum(float(value.get(k, 0)) for k in ("price", "ontime", "lead", "quality"))
        if abs(total - 1.0) > 0.01:
            raise ValidationFailed("Supplier score weights must add up to 1.0")
    return value


def set_many(db: Session, values: dict[str, Any], user: User | None) -> dict[str, Any]:
    for key, value in values.items():
        value = _validate(key, value)
        row = db.get(Setting, key)
        before = None if row is None else {"value": row.value}
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
        audit.record(db, user, "update", "settings", key, before, {"value": value})
    db.commit()
    return get_all(db)
