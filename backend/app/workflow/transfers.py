"""Stock transfer between locations (spec 8.6): request → approve → dispatch → receive."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import now
from app.models.core import User
from app.models.inventory import Batch, MovementType, StockTransfer, StockTransferLine
from app.services import audit, numbering, stock
from app.workflow.engine import record_initial, transition
from app.workflow.machines import TR, stock_transfer


def create(
    db: Session,
    *,
    from_location_id: int,
    to_location_id: int,
    lines: list[dict[str, Any]],
    note: str | None,
    user: User | None,
    actor_type: str | None = None,
) -> StockTransfer:
    if from_location_id == to_location_id:
        raise ValidationFailed("Source and destination must be different locations")
    stock.check_location(db, from_location_id)
    stock.check_location(db, to_location_id)
    if not lines:
        raise ValidationFailed("Add at least one product to transfer")
    tr = StockTransfer(
        transfer_no=numbering.next_number(db, StockTransfer.transfer_no, "TR"),
        from_location_id=from_location_id,
        to_location_id=to_location_id,
        note=note,
        requested_by=user.id if user else None,
        status=TR.REQUESTED,
    )
    for ln in lines:
        product = stock.get_product(db, int(ln["product_id"]))
        qty = float(ln["qty"])
        if qty <= 0:
            raise ValidationFailed("Quantities must be greater than zero")
        tr.lines.append(StockTransferLine(product_id=product.id, batch_id=ln.get("batch_id"), qty=qty))
    db.add(tr)
    db.flush()
    record_initial(db, stock_transfer, tr, actor=user, actor_type=actor_type, note=note)
    audit.created(db, user, tr)
    db.commit()
    return tr


def get(db: Session, transfer_id: int) -> StockTransfer:
    tr = db.get(StockTransfer, transfer_id)
    if not tr:
        raise NotFound("Transfer not found")
    return tr


def approve(db: Session, tr: StockTransfer, user: User) -> StockTransfer:
    transition(db, stock_transfer, tr, TR.APPROVED, actor=user)
    tr.approved_by = user.id
    db.commit()
    return tr


def cancel(db: Session, tr: StockTransfer, user: User, reason: str | None) -> StockTransfer:
    transition(db, stock_transfer, tr, TR.CANCELLED, actor=user, note=reason)
    db.commit()
    return tr


def dispatch(db: Session, tr: StockTransfer, user: User) -> StockTransfer:
    """Pick FEFO at the source; lines are split per batch so the destination receives the same batches."""
    transition(db, stock_transfer, tr, TR.DISPATCHED, actor=user)
    picked: list[StockTransferLine] = []
    for ln in list(tr.lines):
        product = stock.get_product(db, ln.product_id)
        picks = stock.issue(
            db,
            product=product,
            location_id=tr.from_location_id,
            qty=ln.qty,
            movement_type=MovementType.TRANSFER_OUT,
            user=user,
            ref_type="transfer",
            ref_id=tr.id,
            batch_id=ln.batch_id,
            note=f"Transfer {tr.transfer_no}",
        )
        for batch, qty in picks:
            picked.append(StockTransferLine(product_id=ln.product_id, batch_id=batch.id, qty=qty))
    tr.lines.clear()
    db.flush()
    tr.lines.extend(picked)
    tr.dispatched_at = now()
    db.commit()
    return tr


def receive(db: Session, tr: StockTransfer, user: User) -> StockTransfer:
    transition(db, stock_transfer, tr, TR.RECEIVED, actor=user)
    for ln in tr.lines:
        src = db.get(Batch, ln.batch_id) if ln.batch_id else None
        product = stock.get_product(db, ln.product_id)
        stock.receive(
            db,
            product=product,
            location_id=tr.to_location_id,
            qty=ln.qty,
            batch_no=src.batch_no if src else None,
            expiry_date=src.expiry_date if src else None,
            unit_cost=src.cost_price if src else None,
            user=user,
            ref_type="transfer",
            ref_id=tr.id,
            supplier_id=src.supplier_id if src else None,
            movement_type=MovementType.TRANSFER_IN,
            note=f"Transfer {tr.transfer_no}",
        )
    tr.received_at = now()
    db.commit()
    return tr
