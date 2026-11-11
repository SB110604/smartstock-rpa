"""Role-based dashboard data (spec 9.2)."""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.timeutil import now, today
from app.models.ai import Alert, SupplierScore
from app.models.catalog import Product, Supplier
from app.models.core import Role, User
from app.models.inventory import Batch, StockCount
from app.models.purchasing import PurchaseOrder, PurchaseRequest
from app.services import expiry, performance, stock
from app.workflow import approvals
from app.workflow.machines import PO, PR


def stock_value(db: Session) -> float:
    v = db.scalar(select(func.coalesce(func.sum(Batch.qty_on_hand * Batch.cost_price), 0)).where(
        Batch.qty_on_hand > 0, Batch.is_blocked.is_(False),
        (Batch.expiry_date.is_(None)) | (Batch.expiry_date > today())))
    return round(float(v or 0), 2)


def kpis(db: Session) -> dict[str, Any]:
    levels = stock.levels(db)
    products = list(db.scalars(select(Product).where(Product.is_active.is_(True))).unique())
    below = sum(1 for p in products if p.reorder_point is not None
                and levels.get(p.id, {}).get("available", 0) <= p.reorder_point and levels.get(p.id, {}).get("on_hand", 0) > 0)
    out = sum(1 for p in products if levels.get(p.id, {}).get("on_hand", 0) <= 0)
    near = db.scalar(select(func.coalesce(func.sum(Batch.qty_on_hand * Batch.cost_price), 0)).where(
        Batch.qty_on_hand > 0, Batch.expiry_date > today(), Batch.expiry_date <= today() + timedelta(days=30)))
    pending = db.scalar(select(func.count()).select_from(PurchaseRequest).where(PurchaseRequest.status == PR.PENDING)) or 0
    open_pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(PO.OPEN))).unique())
    late = sum(1 for po in open_pos if (po.predicted_date or po.expected_date) and today() > (po.predicted_date or po.expected_date))
    month_start = today().replace(day=1)
    purchases = db.scalar(select(func.coalesce(func.sum(PurchaseOrder.total), 0)).where(
        PurchaseOrder.order_date >= month_start, PurchaseOrder.status.notin_((PO.CANCELLED, PO.REJECTED))))
    cogs = db.scalar(text("SELECT COALESCE(SUM(-qty * unit_cost), 0) FROM stock_movements "
                          "WHERE type = 'sale_out' AND created_at >= :since"), {"since": now() - timedelta(days=365)})
    value = stock_value(db)
    perf = performance.overview(db, weeks=12)["totals"]
    return {"stock_value": value, "below_rop": below, "out_of_stock": out, "near_expiry_value": round(float(near or 0), 2),
            "pending_approvals": pending, "open_pos": len(open_pos), "late_deliveries": late,
            "month_purchases": round(float(purchases or 0), 2),
            "inventory_turnover": round(float(cogs or 0) / value, 1) if value else None,
            "ai_acceptance_pct": perf["acceptance_pct"]}


def sales_vs_forecast(db: Session, days: int = 30, ahead: int = 14) -> list[dict[str, Any]]:
    start = today() - timedelta(days=days)
    actual = dict(db.execute(text("""
        SELECT (s.sold_at AT TIME ZONE :tz)::date, SUM(l.qty) FROM sale_lines l JOIN sales s ON s.id = l.sale_id
        WHERE s.sold_at >= :start GROUP BY 1"""), {"tz": env.TZ, "start": start}).all())
    fc = dict(db.execute(text("SELECT date, SUM(predicted_qty) FROM forecasts WHERE date >= :start AND date < :end GROUP BY 1"),
                         {"start": start, "end": today() + timedelta(days=ahead)}).all())
    out = []
    for i in range(days + ahead):
        d = start + timedelta(days=i)
        out.append({"date": d, "actual": float(actual[d]) if d in actual and d < today() else None,
                    "forecast": round(float(fc[d]), 1) if d in fc else None})
    return out


def stock_value_trend(db: Session, days: int = 90) -> list[dict[str, Any]]:
    """Reconstruct daily closing stock value by unwinding movements backwards from today's value."""
    rows = dict(db.execute(text("""
        SELECT (created_at AT TIME ZONE :tz)::date, SUM(qty * unit_cost) FROM stock_movements
        WHERE created_at >= :since GROUP BY 1"""), {"tz": env.TZ, "since": now() - timedelta(days=days)}).all())
    value = stock_value(db)
    out = []
    for i in range(days):
        d = today() - timedelta(days=i)
        out.append({"date": d, "value": round(max(value, 0.0), 2)})
        value -= float(rows.get(d, 0) or 0)
    return out[::-1]


def fast_movers(db: Session, days: int = 30, limit: int = 10) -> list[dict[str, Any]]:
    rows = db.execute(text("""
        SELECT p.id, p.name, p.unit, SUM(l.qty) q, SUM(l.line_total) v FROM sale_lines l JOIN sales s ON s.id = l.sale_id
        JOIN products p ON p.id = l.product_id WHERE s.sold_at >= :since GROUP BY 1, 2, 3 ORDER BY q DESC LIMIT :n"""),
                      {"since": now() - timedelta(days=days), "n": limit}).all()
    return [{"product_id": r[0], "product": r[1], "unit": r[2], "qty": float(r[3]), "revenue": round(float(r[4]), 2)} for r in rows]


def expiry_by_week(db: Session, weeks: int = 8) -> list[dict[str, Any]]:
    buckets: dict[str, float] = {}
    for r in expiry.assess(db, include_ok=True):
        if 0 < r["days_to_expiry"] <= weeks * 7:
            wk = f"W{(r['days_to_expiry'] - 1) // 7 + 1}"
            buckets[wk] = round(buckets.get(wk, 0.0) + r["value"], 2)
    return [{"week": f"W{i}", "value": buckets.get(f"W{i}", 0.0)} for i in range(1, weeks + 1)]


def supplier_on_time(db: Session) -> list[dict[str, Any]]:
    sub = select(SupplierScore.supplier_id, func.max(SupplierScore.computed_at).label("m")).group_by(SupplierScore.supplier_id).subquery()
    rows = db.execute(select(Supplier.name, SupplierScore.on_time_pct, SupplierScore.total_score)
                      .join(sub, (SupplierScore.supplier_id == sub.c.supplier_id) & (SupplierScore.computed_at == sub.c.m))
                      .join(Supplier, Supplier.id == SupplierScore.supplier_id).order_by(SupplierScore.on_time_pct.desc())).all()
    return [{"supplier": n, "on_time_pct": round(o, 1), "score": round(s, 1)} for n, o, s in rows]


def management(db: Session, user: User) -> dict[str, Any]:
    alerts = db.scalars(select(Alert).where(Alert.status == "open").order_by(
        func.array_position(["critical", "warning", "info"], Alert.severity), Alert.created_at.desc()).limit(6))
    pending = list(db.scalars(select(PurchaseRequest).where(PurchaseRequest.status == PR.PENDING)
                              .order_by(PurchaseRequest.created_at)).unique())
    mine = [pr for pr in pending if (c := approvals.current_approval(pr)) and (user.role == Role.ADMIN or c.approver_role == user.role)]
    return {
        "kpis": kpis(db),
        "charts": {"sales_vs_forecast": sales_vs_forecast(db), "stock_value_trend": stock_value_trend(db),
                   "fast_movers": fast_movers(db), "expiry_by_week": expiry_by_week(db), "supplier_on_time": supplier_on_time(db)},
        "alerts": [{"id": a.id, "type": a.type, "severity": a.severity, "message": a.message, "created_at": a.created_at,
                    "product_id": a.product_id, "ref_type": a.ref_type, "ref_id": a.ref_id} for a in alerts],
        "approvals": [{"id": pr.id, "product": pr.product.name, "qty": pr.final_qty or pr.suggested_qty, "unit": pr.product.unit,
                       "est_total": pr.est_total, "created_by": pr.created_by, "created_at": pr.created_at}
                      for pr in (mine or pending)[:6]],
    }


def staff(db: Session) -> dict[str, Any]:
    to_receive = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_((PO.DISPATCHED, PO.PARTIAL, PO.CONFIRMED)))
                                 .order_by(PurchaseOrder.supplier_eta.asc().nulls_last(), PurchaseOrder.expected_date)).unique())
    counts = list(db.scalars(select(StockCount).where(StockCount.status == "in_progress")).unique())
    exp = [r for r in expiry.assess(db) if r["bucket"] in ("expired", "critical") and r["at_risk"]]
    return {
        "receive": [{"id": po.id, "po_no": po.po_no, "supplier": po.supplier.name, "status": po.status,
                     "eta": po.supplier_eta or po.expected_date, "lines": len(po.lines)} for po in to_receive[:10]],
        "counts": [{"id": c.id, "location": c.location.name, "lines": len(c.lines),
                    "counted": sum(1 for ln in c.lines if ln.counted_qty is not None)} for c in counts],
        "expiring": [{"batch_id": r["batch_id"], "product": r["product"], "batch_no": r["batch_no"], "qty": r["qty"],
                      "unit": r["unit"], "days_to_expiry": r["days_to_expiry"], "suggestion": r["suggestion"]} for r in exp[:10]],
        "summary": {"to_receive": len(to_receive), "counts": len(counts), "expiring": len(exp),
                    "out_of_stock": kpis(db)["out_of_stock"]},
    }
