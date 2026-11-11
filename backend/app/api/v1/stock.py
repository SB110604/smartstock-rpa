from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select

from app.core.deps import DB, require
from app.core.errors import Forbidden, NotFound
from app.core.pagination import PageParams, apply_sort, page_params, paginate
from app.core.permissions import allowed
from app.core.timeutil import start_of_day, today
from app.models.catalog import Product
from app.models.core import User
from app.models.inventory import Batch, StockMovement
from app.schemas.common import Page
from app.schemas.stock import AdjustIn, BatchOut, MarkdownIn, MovementOut, StockInIn, StockOutIn, WriteOffIn
from app.services import audit, stock
from app.services import settings as settings_svc

router = APIRouter(prefix="/stock", tags=["stock"])
Reader = Annotated[User, Depends(require("stock.read"))]
Mover = Annotated[User, Depends(require("stock.move"))]
Adjuster = Annotated[User, Depends(require("stock.adjust"))]
Approver = Annotated[User, Depends(require("stock.approve"))]


def batch_out(b: Batch) -> BatchOut:
    o = BatchOut.model_validate(b)
    o.product_name, o.product_sku, o.location_name = b.product.name, b.product.sku, b.location.name
    o.days_to_expiry = (b.expiry_date - today()).days if b.expiry_date else None
    return o


def movement_out(
    m: StockMovement, users: dict[int, str] | None = None, batches: dict[int, str] | None = None
) -> MovementOut:
    o = MovementOut.model_validate(m)
    o.product_name = m.product.name
    o.user_name = (users or {}).get(m.user_id or 0)
    o.batch_no = (batches or {}).get(m.batch_id or 0)
    return o


@router.get("/lookup")
def lookup(code: str, user: Reader, db: DB, location_id: int | None = None) -> dict[str, Any]:
    """Resolve a scanned barcode / SKU / batch QR to the product, batch and current stock."""
    product, batch = stock.find_by_code(db, code)
    if not product:
        raise NotFound(f"No product matches '{code}'")
    return {
        "product": {
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
            "barcode": product.barcode,
            "unit": product.unit,
            "selling_price": product.selling_price,
            "cost_price": product.cost_price,
            "gst_rate": product.gst_rate,
            "is_perishable": product.is_perishable,
            "shelf_life_days": product.shelf_life_days,
            "pack_size": product.pack_size,
        },
        "batch": batch_out(batch).model_dump() if batch else None,
        "stock": stock.position(db, product.id, location_id),
    }


@router.post("/in", response_model=BatchOut, status_code=201)
def stock_in(body: StockInIn, user: Mover, db: DB) -> BatchOut:
    product = stock.get_product(db, body.product_id)
    batch = stock.receive(
        db,
        product=product,
        location_id=body.location_id,
        qty=body.qty,
        batch_no=body.batch_no,
        expiry_date=body.expiry_date,
        unit_cost=body.cost_price,
        user=user,
        ref_type="manual_in",
        supplier_id=body.supplier_id,
        note=body.note,
    )
    audit.record(db, user, "stock_in", "batches", batch.id, None, {"product_id": product.id, "qty": body.qty})
    db.commit()
    return batch_out(batch)


@router.post("/out")
def stock_out(body: StockOutIn, user: Mover, db: DB) -> dict[str, Any]:
    if body.type == "adjustment" and not allowed(user.role, "stock.adjust"):
        raise Forbidden("Adjustments need a manager")
    product = stock.get_product(db, body.product_id)
    picks = stock.issue(
        db,
        product=product,
        location_id=body.location_id,
        qty=body.qty,
        movement_type=body.type,
        user=user,
        ref_type="manual_out",
        note=body.reason,
        batch_id=body.batch_id,
    )
    audit.record(
        db,
        user,
        "stock_out",
        "products",
        product.id,
        None,
        {"qty": body.qty, "type": body.type, "batches": [b.id for b, _ in picks]},
    )
    db.commit()
    return {
        "picked": [
            {"batch_id": b.id, "batch_no": b.batch_no, "expiry_date": b.expiry_date, "qty": q}
            for b, q in picks
        ],
        "stock": stock.position(db, product.id, body.location_id),
    }


@router.post("/adjust")
def adjust(body: AdjustIn, user: Adjuster, db: DB) -> dict[str, Any]:
    batch = stock.lock_batch(db, body.batch_id)
    if not batch:
        raise NotFound("Batch not found")
    m = stock.adjust_batch(db, batch=batch, new_qty=body.new_qty, reason=body.reason, user=user)
    db.commit()
    return {"batch": batch_out(batch), "delta": m.qty if m else 0}


@router.post("/write-off")
def write_off(body: WriteOffIn, user: Approver, db: DB) -> dict[str, Any]:
    batch = stock.lock_batch(db, body.batch_id)
    if not batch:
        raise NotFound("Batch not found")
    m = stock.write_off(db, batch=batch, qty=body.qty, reason=body.reason, user=user)
    db.commit()
    return {"batch": batch_out(batch), "written_off": -m.qty, "value": round(-m.qty * batch.cost_price, 2)}


@router.post("/markdown", response_model=BatchOut)
def markdown(body: MarkdownIn, user: Approver, db: DB) -> BatchOut:
    batch = db.get(Batch, body.batch_id)
    if not batch:
        raise NotFound("Batch not found")
    audit.apply_update(db, user, batch, {"markdown_pct": body.markdown_pct})
    db.commit()
    return batch_out(batch)


@router.get("/movements", response_model=Page[MovementOut])
def movements(
    user: Reader,
    db: DB,
    p: Annotated[PageParams, Depends(page_params)],
    product_id: int | None = None,
    location_id: int | None = None,
    type: str | None = None,
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(StockMovement)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if location_id:
        stmt = stmt.where(StockMovement.location_id == location_id)
    if type:
        stmt = stmt.where(StockMovement.type == type)
    if user_id:
        stmt = stmt.where(StockMovement.user_id == user_id)
    if date_from:
        stmt = stmt.where(StockMovement.created_at >= start_of_day(date_from))
    if date_to:
        stmt = stmt.where(StockMovement.created_at < start_of_day(date_to + timedelta(days=1)))
    stmt = apply_sort(
        stmt,
        p.sort,
        {"created_at": StockMovement.created_at, "qty": StockMovement.qty},
        StockMovement.created_at.desc(),
    )
    page = paginate(db, stmt, p)
    uids = {m.user_id for m in page["items"] if m.user_id}
    bids = {m.batch_id for m in page["items"] if m.batch_id}
    users = dict(db.execute(select(User.id, User.name).where(User.id.in_(uids))).all()) if uids else {}
    batches = (
        dict(db.execute(select(Batch.id, Batch.batch_no).where(Batch.id.in_(bids))).all()) if bids else {}
    )
    page["items"] = [movement_out(m, users, batches) for m in page["items"]]
    return page


@router.get("/batches", response_model=Page[BatchOut])
def batches(
    user: Reader,
    db: DB,
    p: Annotated[PageParams, Depends(page_params)],
    product_id: int | None = None,
    location_id: int | None = None,
    bucket: str | None = None,
    q: str | None = None,
    include_empty: bool = False,
) -> dict[str, Any]:
    """bucket: expired | critical | warning | ok (thresholds from settings)."""
    th = settings_svc.get(db, "expiry_thresholds")
    d0 = today()
    stmt = select(Batch).join(Product, Product.id == Batch.product_id)
    if not include_empty:
        stmt = stmt.where(Batch.qty_on_hand > 0)
    if product_id:
        stmt = stmt.where(Batch.product_id == product_id)
    if location_id:
        stmt = stmt.where(Batch.location_id == location_id)
    if q:
        stmt = stmt.where(
            or_(Product.name.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%"), Batch.batch_no.ilike(f"%{q}%"))
        )
    if bucket == "expired":
        stmt = stmt.where(Batch.expiry_date <= d0)
    elif bucket == "critical":
        stmt = stmt.where(Batch.expiry_date > d0, Batch.expiry_date <= d0 + timedelta(days=th["critical"]))
    elif bucket == "warning":
        stmt = stmt.where(
            Batch.expiry_date > d0 + timedelta(days=th["critical"]),
            Batch.expiry_date <= d0 + timedelta(days=th["warning"]),
        )
    elif bucket == "ok":
        stmt = stmt.where(
            or_(Batch.expiry_date.is_(None), Batch.expiry_date > d0 + timedelta(days=th["warning"]))
        )
    stmt = apply_sort(
        stmt,
        p.sort,
        {
            "expiry_date": Batch.expiry_date,
            "qty_on_hand": Batch.qty_on_hand,
            "received_at": Batch.received_at,
            "product": Product.name,
        },
        Batch.expiry_date.asc().nulls_last(),
    )
    return paginate(db, stmt, p, batch_out)
