"""Stock ledger: every quantity change is a batch update plus a signed StockMovement row.

FEFO (first-expiry-first-out) is applied automatically to every outbound movement (spec 7.2)."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.timeutil import now, today
from app.models.catalog import Product
from app.models.core import Location, User
from app.models.inventory import Batch, MovementType, StockMovement
from app.models.purchasing import PoLine, PurchaseOrder
from app.services import audit
from app.workflow.machines import PO

EPS = 1e-9


def _sellable_filter(on: date | None = None) -> Any:
    d = on or today()
    return and_(
        Batch.qty_on_hand > EPS,
        Batch.is_blocked.is_(False),
        or_(Batch.expiry_date.is_(None), Batch.expiry_date > d),
    )


def fefo_batches(db: Session, product_id: int, location_id: int, lock: bool = True) -> list[Batch]:
    """Sellable batches in pick order: earliest expiry first (no-expiry last), then oldest receipt."""
    stmt = (
        select(Batch)
        .where(Batch.product_id == product_id, Batch.location_id == location_id, _sellable_filter())
        .order_by(Batch.expiry_date.asc().nulls_last(), Batch.received_at.asc(), Batch.id.asc())
    )
    if lock:
        stmt = stmt.with_for_update(of=Batch)
    return list(db.scalars(stmt).unique())


def plan_fefo(batches: list[Batch], qty: float) -> list[tuple[Batch, float]]:
    """Pure FEFO allocation over already-ordered batches. Raises if stock is insufficient."""
    remaining = qty
    picks: list[tuple[Batch, float]] = []
    for b in batches:
        if remaining <= EPS:
            break
        take = min(b.qty_on_hand, remaining)
        if take > EPS:
            picks.append((b, round(take, 3)))
            remaining -= take
    if remaining > EPS:
        available = sum(b.qty_on_hand for b in batches)
        raise Conflict(
            f"Insufficient stock: requested {qty:g}, available {available:g}", code="insufficient_stock"
        )
    return picks


def on_hand_map(
    db: Session, location_id: int | None = None, product_ids: list[int] | None = None
) -> dict[tuple[int, int], float]:
    """{(product_id, location_id): sellable qty} — excludes expired and blocked batches."""
    stmt = select(Batch.product_id, Batch.location_id, func.sum(Batch.qty_on_hand)).where(_sellable_filter())
    if location_id:
        stmt = stmt.where(Batch.location_id == location_id)
    if product_ids is not None:
        stmt = stmt.where(Batch.product_id.in_(product_ids))
    return {
        (p, loc): float(q or 0)
        for p, loc, q in db.execute(stmt.group_by(Batch.product_id, Batch.location_id))
    }


def on_order_map(
    db: Session, location_id: int | None = None, product_ids: list[int] | None = None
) -> dict[tuple[int, int], float]:
    """{(product_id, location_id): qty ordered on open POs but not yet received}."""
    stmt = (
        select(
            PoLine.product_id,
            PurchaseOrder.location_id,
            func.sum(PoLine.qty - PoLine.received_qty - PoLine.damaged_qty),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
        .where(PurchaseOrder.status.in_(PO.OPEN))
    )
    if location_id:
        stmt = stmt.where(PurchaseOrder.location_id == location_id)
    if product_ids is not None:
        stmt = stmt.where(PoLine.product_id.in_(product_ids))
    rows = db.execute(stmt.group_by(PoLine.product_id, PurchaseOrder.location_id))
    return {(p, loc): max(0.0, float(q or 0)) for p, loc, q in rows}


def position(db: Session, product_id: int, location_id: int | None = None) -> dict[str, float]:
    oh = on_hand_map(db, location_id, [product_id])
    oo = on_order_map(db, location_id, [product_id])
    on_hand = sum(v for (p, _), v in oh.items() if p == product_id)
    on_order = sum(v for (p, _), v in oo.items() if p == product_id)
    return {
        "on_hand": round(on_hand, 3),
        "on_order": round(on_order, 3),
        "available": round(on_hand + on_order, 3),
    }


def levels(db: Session, location_id: int | None = None) -> dict[int, dict[str, float]]:
    """Per-product totals (optionally for one location): on_hand, on_order, available = on_hand + on_order."""
    out: dict[int, dict[str, float]] = defaultdict(
        lambda: {"on_hand": 0.0, "on_order": 0.0, "available": 0.0}
    )
    for (p, _), q in on_hand_map(db, location_id).items():
        out[p]["on_hand"] += q
    for (p, _), q in on_order_map(db, location_id).items():
        out[p]["on_order"] += q
    for v in out.values():
        v["available"] = v["on_hand"] + v["on_order"]
    return out


def record_movement(
    db: Session,
    *,
    product_id: int,
    location_id: int,
    batch: Batch | None,
    mtype: str,
    qty: float,
    unit_cost: float,
    user: User | None,
    ref_type: str | None,
    ref_id: int | None,
    note: str | None,
    at: datetime | None = None,
) -> StockMovement:
    m = StockMovement(
        product_id=product_id,
        batch_id=batch.id if batch else None,
        location_id=location_id,
        type=mtype,
        qty=round(qty, 3),
        unit_cost=unit_cost,
        reference_type=ref_type,
        reference_id=ref_id,
        user_id=user.id if user else None,
        note=note,
    )
    if at:
        m.created_at = at
    db.add(m)
    return m


def lock_batch(db: Session, batch_id: int) -> Batch | None:
    """SELECT … FOR UPDATE OF batches (eager-loaded joins must not be locked)."""
    return db.scalar(select(Batch).where(Batch.id == batch_id).with_for_update(of=Batch))


def get_product(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if not p:
        raise NotFound("Product not found")
    return p


def check_location(db: Session, location_id: int) -> Location:
    loc = db.get(Location, location_id)
    if not loc:
        raise NotFound("Location not found")
    return loc


def receive(
    db: Session,
    *,
    product: Product,
    location_id: int,
    qty: float,
    batch_no: str | None,
    expiry_date: date | None,
    unit_cost: float | None,
    user: User | None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    supplier_id: int | None = None,
    grn_line_id: int | None = None,
    note: str | None = None,
    movement_type: str = MovementType.PURCHASE_IN,
    at: datetime | None = None,
) -> Batch:
    if qty <= 0:
        raise ValidationFailed("Quantity must be greater than zero")
    check_location(db, location_id)
    received_at = at or now()
    if product.is_perishable and expiry_date is None:
        if not product.shelf_life_days:
            raise ValidationFailed(f"Expiry date is required for perishable product {product.name}")
        expiry_date = received_at.date() + timedelta(days=product.shelf_life_days)
    batch_no = (batch_no or "").strip() or f"B{received_at:%y%m%d}-{product.id}"
    cost = product.cost_price if unit_cost is None else unit_cost
    batch = db.scalar(
        select(Batch)
        .where(
            Batch.product_id == product.id,
            Batch.location_id == location_id,
            Batch.batch_no == batch_no,
            Batch.expiry_date.is_(None) if expiry_date is None else Batch.expiry_date == expiry_date,
        )
        .with_for_update(of=Batch)
    )
    if batch:
        total_qty = batch.qty_on_hand + qty
        batch.cost_price = (
            round((batch.cost_price * batch.qty_on_hand + cost * qty) / total_qty, 2) if total_qty else cost
        )
        batch.qty_on_hand = round(total_qty, 3)
    else:
        batch = Batch(
            product_id=product.id,
            location_id=location_id,
            batch_no=batch_no,
            expiry_date=expiry_date,
            qty_on_hand=round(qty, 3),
            cost_price=cost,
            received_at=received_at,
            grn_line_id=grn_line_id,
            supplier_id=supplier_id,
        )
        db.add(batch)
    db.flush()
    record_movement(
        db,
        product_id=product.id,
        location_id=location_id,
        batch=batch,
        mtype=movement_type,
        qty=qty,
        unit_cost=cost,
        user=user,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
        at=at,
    )
    return batch


def _negative_attempt(
    db: Session, user: User | None, product: Product, location_id: int, qty: float, err: Conflict
) -> None:
    # Recorded in its own audit row: the anomaly agent counts these (spec 7.7, "negative-stock attempts").
    audit.record(
        db,
        user,
        "negative_stock_attempt",
        "products",
        product.id,
        None,
        {"location_id": location_id, "requested": qty, "message": err.detail},
    )
    db.commit()


def issue(
    db: Session,
    *,
    product: Product,
    location_id: int,
    qty: float,
    movement_type: str,
    user: User | None,
    ref_type: str | None = None,
    ref_id: int | None = None,
    note: str | None = None,
    batch_id: int | None = None,
    at: datetime | None = None,
) -> list[tuple[Batch, float]]:
    """Take stock out (sale, write-off, return, transfer) using FEFO unless a specific batch is named."""
    if qty <= 0:
        raise ValidationFailed("Quantity must be greater than zero")
    if batch_id:
        batch = lock_batch(db, batch_id)
        if not batch or batch.product_id != product.id or batch.location_id != location_id:
            raise NotFound("Batch not found for this product and location")
        if movement_type == MovementType.SALE_OUT and (
            batch.is_blocked or (batch.expiry_date and batch.expiry_date <= today())
        ):
            raise Conflict("This batch is expired or blocked and cannot be sold", code="batch_blocked")
        candidates = [batch]
    else:
        candidates = fefo_batches(db, product.id, location_id)
    try:
        picks = plan_fefo(candidates, qty)
    except Conflict as err:
        db.rollback()
        _negative_attempt(db, user, product, location_id, qty, err)
        raise
    for batch, take in picks:
        batch.qty_on_hand = round(batch.qty_on_hand - take, 3)
        record_movement(
            db,
            product_id=product.id,
            location_id=location_id,
            batch=batch,
            mtype=movement_type,
            qty=-take,
            unit_cost=batch.cost_price,
            user=user,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
            at=at,
        )
    db.flush()
    return picks


def adjust_batch(
    db: Session, *, batch: Batch, new_qty: float, reason: str, user: User | None
) -> StockMovement | None:
    if not reason or not reason.strip():
        raise ValidationFailed("A reason is required for stock adjustments")
    if new_qty < 0:
        raise ValidationFailed("Quantity cannot be negative")
    delta = round(new_qty - batch.qty_on_hand, 3)
    if abs(delta) < EPS:
        return None
    before = audit.snapshot(batch)
    batch.qty_on_hand = round(new_qty, 3)
    m = record_movement(
        db,
        product_id=batch.product_id,
        location_id=batch.location_id,
        batch=batch,
        mtype=MovementType.ADJUSTMENT,
        qty=delta,
        unit_cost=batch.cost_price,
        user=user,
        ref_type="adjustment",
        ref_id=None,
        note=reason.strip(),
    )
    db.flush()
    audit.record(db, user, "update", "batches", batch.id, before, audit.snapshot(batch))
    return m


def write_off(
    db: Session, *, batch: Batch, qty: float | None, reason: str, user: User | None
) -> StockMovement:
    take = batch.qty_on_hand if qty is None else qty
    if take <= 0 or take > batch.qty_on_hand + EPS:
        raise ValidationFailed("Write-off quantity must be between 0 and the batch quantity")
    batch.qty_on_hand = round(batch.qty_on_hand - take, 3)
    if batch.qty_on_hand <= EPS:
        batch.is_blocked = True
    m = record_movement(
        db,
        product_id=batch.product_id,
        location_id=batch.location_id,
        batch=batch,
        mtype=MovementType.WRITE_OFF,
        qty=-take,
        unit_cost=batch.cost_price,
        user=user,
        ref_type="write_off",
        ref_id=batch.id,
        note=reason,
    )
    db.flush()
    audit.record(db, user, "write_off", "batches", batch.id, None, {"qty": take, "reason": reason})
    return m


def find_by_code(db: Session, code: str) -> tuple[Product | None, Batch | None]:
    """Resolve a scanned code: barcode, SKU, or batch label payload 'SKU|BATCHNO'."""
    code = (code or "").strip()
    if not code:
        return None, None
    sku, _, batch_no = code.partition("|")
    product = db.scalar(select(Product).where(or_(Product.barcode == sku, Product.sku == sku)))
    batch = None
    if product and batch_no:
        batch = db.scalar(
            select(Batch)
            .where(Batch.product_id == product.id, Batch.batch_no == batch_no)
            .order_by(Batch.qty_on_hand.desc())
        )
    return product, batch
