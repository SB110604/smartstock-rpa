"""Expiry assessment (spec 7.2) shared by the Expiry agent and the Expiry page."""

from datetime import timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.timeutil import now, today
from app.models.core import Location
from app.models.inventory import Batch
from app.services import settings as settings_svc

SALES_WINDOW = 28


def avg_daily_sales(db: Session) -> dict[tuple[int, int], float]:
    """{(product_id, location_id): mean units/day over the last 28 days}."""
    rows = db.execute(text("""
        SELECT l.product_id, s.location_id, SUM(l.qty) FROM sale_lines l JOIN sales s ON s.id = l.sale_id
        WHERE s.sold_at >= :since GROUP BY 1, 2
    """), {"since": now() - timedelta(days=SALES_WINDOW)}).all()
    return {(p, loc): float(q) / SALES_WINDOW for p, loc, q in rows}


def bucket(days: int, th: dict[str, int]) -> str:
    if days <= 0:
        return "expired"
    if days <= th["critical"]:
        return "critical"
    if days <= th["warning"]:
        return "warning"
    return "ok"


def assess(db: Session, include_ok: bool = False) -> list[dict[str, Any]]:
    th = settings_svc.get(db, "expiry_thresholds")
    md = settings_svc.get(db, "markdown")
    sales = avg_daily_sales(db)
    locations = {loc.id: loc for loc in db.scalars(select(Location))}
    horizon = today() + timedelta(days=int(th["warning"]))
    stmt = select(Batch).where(Batch.qty_on_hand > 0, Batch.expiry_date.is_not(None))
    if not include_ok:
        stmt = stmt.where(Batch.expiry_date <= horizon)
    out = []
    for b in db.scalars(stmt.order_by(Batch.expiry_date)).unique():
        assert b.expiry_date is not None
        days = (b.expiry_date - today()).days
        bk = bucket(days, th)
        rate = sales.get((b.product_id, b.location_id), 0.0)
        projected = rate * max(days, 0)
        at_risk = bk == "expired" or projected < b.qty_on_hand
        surplus = max(0.0, b.qty_on_hand - projected)
        actions: list[str] = []
        suggestion = ""
        if bk == "expired":
            actions = ["write_off", "return"]
            suggestion = "Expired — blocked from sale. Write off or return to supplier."
        elif bk == "critical" and at_risk:
            actions = ["markdown", "return", "write_off"]
            suggestion = f"Only {projected:.0f} of {b.qty_on_hand:g} will sell before expiry — apply a {md['critical_pct']}% markdown."
        elif bk == "warning" and at_risk:
            other = [loc for lid, loc in locations.items() if lid != b.location_id
                     and sales.get((b.product_id, lid), 0) * days > sales.get((b.product_id, b.location_id), 0) * days]
            actions = ["markdown", "transfer"] if other else ["markdown"]
            suggestion = (f"Projected sell-through {projected:.0f} of {b.qty_on_hand:g}: apply a {md['warning_pct']}% markdown"
                          + (f" or transfer to {other[0].name}" if other else "") + ".")
        out.append({
            "batch_id": b.id, "product_id": b.product_id, "product": b.product.name, "sku": b.product.sku,
            "unit": b.product.unit, "batch_no": b.batch_no, "location_id": b.location_id, "location": b.location.name,
            "expiry_date": b.expiry_date, "days_to_expiry": days, "bucket": bk, "qty": b.qty_on_hand,
            "value": round(b.qty_on_hand * b.cost_price, 2), "avg_daily_sales": round(rate, 2),
            "projected_sell": round(projected, 1), "surplus": round(surplus, 1), "at_risk": at_risk,
            "markdown_pct": b.markdown_pct, "is_blocked": b.is_blocked, "supplier_id": b.supplier_id,
            "suggested_markdown": md["critical_pct"] if bk == "critical" else (md["warning_pct"] if bk == "warning" else 0),
            "actions": actions, "suggestion": suggestion,
        })
    return out
