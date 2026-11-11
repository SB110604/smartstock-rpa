"""Cycle counts: snapshot system qty per batch → staff enter counted qty → completion posts adjustments."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.timeutil import now
from app.models.catalog import Product
from app.models.core import User
from app.models.inventory import Batch, StockCount, StockCountLine
from app.services import audit, stock


def start(
    db: Session,
    *,
    location_id: int,
    category_id: int | None,
    product_ids: list[int] | None,
    note: str | None,
    user: User,
) -> StockCount:
    stock.check_location(db, location_id)
    count = StockCount(location_id=location_id, note=note, started_by=user.id)
    db.add(count)
    db.flush()
    pstmt = select(Product).where(Product.is_active.is_(True))
    if category_id:
        pstmt = pstmt.where(Product.category_id == category_id)
    if product_ids:
        pstmt = pstmt.where(Product.id.in_(product_ids))
    products = {p.id: p for p in db.scalars(pstmt).unique()}
    if not products:
        raise ValidationFailed("No products match this count")
    batches = db.scalars(
        select(Batch)
        .where(Batch.location_id == location_id, Batch.product_id.in_(products), Batch.qty_on_hand > 0)
        .order_by(Batch.product_id, Batch.expiry_date.nulls_last())
    ).unique()
    seen: set[int] = set()
    for b in batches:
        count.lines.append(StockCountLine(product_id=b.product_id, batch_id=b.id, system_qty=b.qty_on_hand))
        seen.add(b.product_id)
    for pid in products:
        if pid not in seen:  # products with no stock are counted too (found stock becomes a new batch)
            count.lines.append(StockCountLine(product_id=pid, batch_id=None, system_qty=0))
    audit.created(db, user, count)
    db.commit()
    return count


def get(db: Session, count_id: int) -> StockCount:
    c = db.get(StockCount, count_id)
    if not c:
        raise NotFound("Stock count not found")
    return c


def record_counts(db: Session, count: StockCount, entries: list[dict[str, Any]], user: User) -> StockCount:
    if count.status != "in_progress":
        raise Conflict("This count is already closed")
    by_id = {line.id: line for line in count.lines}
    for e in entries:
        line = by_id.get(int(e["line_id"]))
        if not line:
            raise NotFound(f"Count line {e['line_id']} not found")
        qty = e.get("counted_qty")
        if qty is not None and float(qty) < 0:
            raise ValidationFailed("Counted quantity cannot be negative")
        line.counted_qty = None if qty is None else float(qty)
        line.variance = None if qty is None else round(float(qty) - line.system_qty, 3)
    db.commit()
    return count


def complete(db: Session, count: StockCount, user: User) -> dict[str, Any]:
    if count.status != "in_progress":
        raise Conflict("This count is already closed")
    missing = [ln.id for ln in count.lines if ln.counted_qty is None]
    if missing:
        raise ValidationFailed(f"{len(missing)} line(s) have no counted quantity yet")
    adjustments = 0
    value = 0.0
    for line in count.lines:
        if abs(line.variance or 0) < 1e-9:
            continue
        reason = f"Stock count #{count.id} variance"
        if line.batch_id:
            batch = stock.lock_batch(db, line.batch_id)
            if batch is None:
                continue
            # Movements since the snapshot are preserved: apply the variance, not the absolute count.
            new_qty = max(0.0, batch.qty_on_hand + (line.variance or 0))
            stock.adjust_batch(db, batch=batch, new_qty=new_qty, reason=reason, user=user)
            value += (line.variance or 0) * batch.cost_price
        elif (line.counted_qty or 0) > 0:
            product = stock.get_product(db, line.product_id)
            stock.receive(
                db,
                product=product,
                location_id=count.location_id,
                qty=line.counted_qty or 0,
                batch_no=f"CNT{count.id}",
                expiry_date=None,
                unit_cost=product.cost_price,
                user=user,
                ref_type="stock_count",
                ref_id=count.id,
                note=reason,
                movement_type="adjustment",
            )
            value += (line.counted_qty or 0) * product.cost_price
        adjustments += 1
    count.status = "completed"
    count.completed_at = now()
    audit.record(
        db,
        user,
        "update",
        "stock_counts",
        count.id,
        {"status": "in_progress"},
        {"status": "completed", "adjustments": adjustments, "variance_value": round(value, 2)},
    )
    db.commit()
    return {"adjustments": adjustments, "variance_value": round(value, 2)}


def variance_report(count: StockCount) -> dict[str, Any]:
    lines = []
    total_value = 0.0
    for ln in count.lines:
        cost = ln.product.cost_price
        val = round((ln.variance or 0) * cost, 2)
        total_value += val
        lines.append(
            {
                "line_id": ln.id,
                "product_id": ln.product_id,
                "product": ln.product.name,
                "sku": ln.product.sku,
                "batch_id": ln.batch_id,
                "system_qty": ln.system_qty,
                "counted_qty": ln.counted_qty,
                "variance": ln.variance,
                "variance_value": val,
            }
        )
    counted = [ln for ln in count.lines if ln.counted_qty is not None]
    return {
        "lines": lines,
        "summary": {
            "lines": len(count.lines),
            "counted": len(counted),
            "with_variance": sum(1 for ln in counted if abs(ln.variance or 0) > 1e-9),
            "variance_value": round(total_value, 2),
            "accuracy_pct": round(
                100 * sum(1 for ln in counted if abs(ln.variance or 0) < 1e-9) / len(counted), 1
            )
            if counted
            else None,
        },
    }
