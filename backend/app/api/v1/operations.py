"""Stock counts, inter-location transfers, sales/billing and the external POS sales API."""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from sqlalchemy import or_, select

from app.core.deps import DB, require
from app.core.errors import NotFound, Unauthorized, ValidationFailed
from app.core.pagination import PageParams, apply_sort, page_params, paginate
from app.core.security import hash_token
from app.core.timeutil import now, start_of_day
from app.models.catalog import Product
from app.models.core import ApiKey, Location, StatusHistory, User
from app.models.inventory import Sale, StockCount, StockTransfer
from app.schemas.common import Page
from app.schemas.stock import (
    CountEntriesIn,
    CountStartIn,
    PosSaleIn,
    ReasonIn,
    SaleIn,
    SaleLineOut,
    SaleOut,
    TransferIn,
)
from app.services import counts, sales
from app.workflow import transfers

router = APIRouter(tags=["operations"])
Mover = Annotated[User, Depends(require("stock.move"))]
Approver = Annotated[User, Depends(require("stock.approve"))]
Reader = Annotated[User, Depends(require("stock.read"))]
SalesWriter = Annotated[User, Depends(require("sales.write"))]
SalesReader = Annotated[User, Depends(require("sales.read"))]


# ------------------------------------------------------------------ stock counts


def count_out(c: StockCount) -> dict[str, Any]:
    return {
        "id": c.id,
        "location_id": c.location_id,
        "location": c.location.name,
        "status": c.status,
        "note": c.note,
        "started_by": c.started_by,
        "created_at": c.created_at,
        "completed_at": c.completed_at,
        **counts.variance_report(c),
    }


@router.get("/stock-counts")
def list_counts(
    user: Reader, db: DB, p: Annotated[PageParams, Depends(page_params)], status: str | None = None
) -> dict[str, Any]:
    stmt = select(StockCount)
    if status:
        stmt = stmt.where(StockCount.status == status)
    page = paginate(db, stmt.order_by(StockCount.created_at.desc()), p)
    page["items"] = [
        {
            "id": c.id,
            "location": c.location.name,
            "status": c.status,
            "note": c.note,
            "created_at": c.created_at,
            "completed_at": c.completed_at,
            **counts.variance_report(c)["summary"],
        }
        for c in page["items"]
    ]
    return page


@router.post("/stock-counts", status_code=201)
def start_count(body: CountStartIn, user: Mover, db: DB) -> dict[str, Any]:
    c = counts.start(
        db,
        location_id=body.location_id,
        category_id=body.category_id,
        product_ids=body.product_ids,
        note=body.note,
        user=user,
    )
    return count_out(c)


@router.get("/stock-counts/{count_id}")
def get_count(count_id: int, user: Reader, db: DB) -> dict[str, Any]:
    return count_out(counts.get(db, count_id))


@router.patch("/stock-counts/{count_id}")
def record_count(count_id: int, body: CountEntriesIn, user: Mover, db: DB) -> dict[str, Any]:
    c = counts.record_counts(db, counts.get(db, count_id), [e.model_dump() for e in body.entries], user)
    return count_out(c)


@router.post("/stock-counts/{count_id}/complete")
def complete_count(count_id: int, user: Approver, db: DB) -> dict[str, Any]:
    c = counts.get(db, count_id)
    result = counts.complete(db, c, user)
    return {**count_out(c), "result": result}


# ------------------------------------------------------------------ transfers


def transfer_out(db: DB, t: StockTransfer, history: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": t.id,
        "transfer_no": t.transfer_no,
        "status": t.status,
        "note": t.note,
        "from_location_id": t.from_location_id,
        "from_location": t.from_location.name,
        "to_location_id": t.to_location_id,
        "to_location": t.to_location.name,
        "created_at": t.created_at,
        "dispatched_at": t.dispatched_at,
        "received_at": t.received_at,
        "lines": [
            {
                "id": ln.id,
                "product_id": ln.product_id,
                "product": ln.product.name,
                "sku": ln.product.sku,
                "batch_id": ln.batch_id,
                "qty": ln.qty,
            }
            for ln in t.lines
        ],
    }
    if history:
        out["history"] = [
            {
                "from": h.from_status,
                "to": h.to_status,
                "note": h.note,
                "actor_type": h.actor_type,
                "actor_id": h.actor_id,
                "at": h.created_at,
            }
            for h in db.scalars(
                select(StatusHistory)
                .where(StatusHistory.entity == "stock_transfer", StatusHistory.entity_id == t.id)
                .order_by(StatusHistory.id)
            )
        ]
    return out


@router.get("/transfers")
def list_transfers(
    user: Reader, db: DB, p: Annotated[PageParams, Depends(page_params)], status: str | None = None
) -> dict[str, Any]:
    stmt = select(StockTransfer)
    if status:
        stmt = stmt.where(StockTransfer.status == status)
    page = paginate(db, stmt.order_by(StockTransfer.created_at.desc()), p)
    page["items"] = [transfer_out(db, t) for t in page["items"]]
    return page


@router.post("/transfers", status_code=201)
def create_transfer(body: TransferIn, user: Mover, db: DB) -> dict[str, Any]:
    t = transfers.create(
        db,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        lines=[ln.model_dump() for ln in body.lines],
        note=body.note,
        user=user,
    )
    return transfer_out(db, t, history=True)


@router.get("/transfers/{transfer_id}")
def get_transfer(transfer_id: int, user: Reader, db: DB) -> dict[str, Any]:
    return transfer_out(db, transfers.get(db, transfer_id), history=True)


@router.post("/transfers/{transfer_id}/approve")
def approve_transfer(transfer_id: int, user: Approver, db: DB) -> dict[str, Any]:
    return transfer_out(db, transfers.approve(db, transfers.get(db, transfer_id), user), history=True)


@router.post("/transfers/{transfer_id}/dispatch")
def dispatch_transfer(transfer_id: int, user: Mover, db: DB) -> dict[str, Any]:
    return transfer_out(db, transfers.dispatch(db, transfers.get(db, transfer_id), user), history=True)


@router.post("/transfers/{transfer_id}/receive")
def receive_transfer(transfer_id: int, user: Mover, db: DB) -> dict[str, Any]:
    return transfer_out(db, transfers.receive(db, transfers.get(db, transfer_id), user), history=True)


@router.post("/transfers/{transfer_id}/cancel")
def cancel_transfer(transfer_id: int, body: ReasonIn, user: Approver, db: DB) -> dict[str, Any]:
    return transfer_out(
        db, transfers.cancel(db, transfers.get(db, transfer_id), user, body.reason), history=True
    )


# ------------------------------------------------------------------ sales


def sale_out(s: Sale) -> SaleOut:
    o = SaleOut.model_validate(s)
    o.lines = [
        SaleLineOut.model_validate(ln).model_copy(update={"product_name": ln.product.name}) for ln in s.lines
    ]
    return o


@router.post("/sales", response_model=SaleOut, status_code=201)
def create_sale(body: SaleIn, user: SalesWriter, db: DB) -> SaleOut:
    s = sales.create_sale(
        db,
        location_id=body.location_id,
        lines=[ln.model_dump() for ln in body.lines],
        channel="manual",
        user=user,
        customer_name=body.customer_name,
    )
    return sale_out(s)


@router.get("/sales", response_model=Page[SaleOut])
def list_sales(
    user: SalesReader,
    db: DB,
    p: Annotated[PageParams, Depends(page_params)],
    q: str | None = None,
    location_id: int | None = None,
    channel: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(Sale)
    if q:
        stmt = stmt.where(or_(Sale.invoice_no.ilike(f"%{q}%"), Sale.customer_name.ilike(f"%{q}%")))
    if location_id:
        stmt = stmt.where(Sale.location_id == location_id)
    if channel:
        stmt = stmt.where(Sale.channel == channel)
    if date_from:
        stmt = stmt.where(Sale.sold_at >= start_of_day(date_from))
    if date_to:
        stmt = stmt.where(Sale.sold_at < start_of_day(date_to + timedelta(days=1)))
    stmt = apply_sort(stmt, p.sort, {"sold_at": Sale.sold_at, "total": Sale.total}, Sale.sold_at.desc())
    return paginate(db, stmt, p, sale_out)


@router.get("/sales/{sale_id}", response_model=SaleOut)
def get_sale(sale_id: int, user: SalesReader, db: DB) -> SaleOut:
    s = db.get(Sale, sale_id)
    if not s:
        raise NotFound("Sale not found")
    return sale_out(s)


@router.post("/integrations/pos/sales", response_model=SaleOut, status_code=201, tags=["integrations"])
def pos_sale(body: PosSaleIn, db: DB, x_api_key: Annotated[str | None, Header()] = None) -> SaleOut:
    """External POS: authenticate with header `X-API-Key: ssk_…` (create keys in Settings → API keys)."""
    if not x_api_key:
        raise Unauthorized("Missing X-API-Key header", code="api_key_missing")
    key = db.scalar(
        select(ApiKey).where(ApiKey.key_hash == hash_token(x_api_key), ApiKey.is_active.is_(True))
    )
    if not key:
        raise Unauthorized("Invalid API key", code="api_key_invalid")
    location_id = body.location_id or key.location_id or db.scalar(select(Location.id).order_by(Location.id))
    if not location_id:
        raise ValidationFailed("No location configured")
    lines = []
    for ln in body.lines:
        code = ln.barcode or ln.sku
        prod = (
            db.scalar(select(Product).where(or_(Product.sku == code, Product.barcode == code)))
            if code
            else None
        )
        if not prod:
            raise ValidationFailed(f"Unknown product '{code}'")
        lines.append({"product_id": prod.id, "qty": ln.qty, "unit_price": ln.unit_price})
    key.last_used_at = now()
    s = sales.create_sale(
        db,
        location_id=location_id,
        lines=lines,
        channel="pos_api",
        user=None,
        invoice_no=body.invoice_no,
        sold_at=body.sold_at,
    )
    return sale_out(s)
