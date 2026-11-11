"""Supplier portal: a supplier user only ever sees its own supplier's purchase orders and invoices."""

import json
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.v1.orders import is_late, line_out, po_out
from app.core.config import settings as env
from app.core.deps import DB, require
from app.core.errors import Forbidden, ValidationFailed
from app.core.pagination import PageParams, page_params, paginate
from app.models.ai import SupplierScore
from app.models.core import User
from app.models.purchasing import OrderStatusHistory, PurchaseOrder, Rfq, RfqSupplier, SupplierInvoice
from app.workflow import purchasing, receiving
from app.workflow.machines import PO

router = APIRouter(prefix="/portal", tags=["supplier portal"])
Supplier_ = Annotated[User, Depends(require("portal.use"))]
MAX_FILE = 10 * 1024 * 1024


class ConfirmIn(BaseModel):
    eta: date | None = None
    note: str | None = Field(None, max_length=500)


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class DispatchIn(BaseModel):
    eta: date
    tracking_ref: str | None = Field(None, max_length=80)
    courier_name: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=500)


def own_po(db: DB, user: User, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if not po or po.supplier_id != user.supplier_id:
        raise Forbidden("This purchase order belongs to another supplier")
    return po


def detail(db: DB, po: PurchaseOrder) -> dict[str, Any]:
    history = db.scalars(select(OrderStatusHistory).where(OrderStatusHistory.po_id == po.id).order_by(OrderStatusHistory.id))
    invoices = list(db.scalars(select(SupplierInvoice).where(SupplierInvoice.po_id == po.id)))
    actions = []
    if po.status == PO.SENT:
        actions = ["confirm", "reject", "dispatch"]
    elif po.status == PO.CONFIRMED:
        actions = ["dispatch"]
    if po.status in (PO.DISPATCHED, PO.PARTIAL, PO.RECEIVED, PO.CONFIRMED) and not invoices:
        actions.append("invoice")
    return {**po_out(po), "lines": [line_out(ln) for ln in po.lines], "actions": actions,
            "timeline": [{"to": h.to_status, "note": h.note, "at": h.created_at} for h in history],
            "invoices": [{"id": i.id, "invoice_no": i.invoice_no, "total": i.total, "status": i.status}
                         for i in invoices]}


@router.get("/summary")
def summary(user: Supplier_, db: DB) -> dict[str, Any]:
    base = select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.supplier_id == user.supplier_id)
    score = db.scalar(select(SupplierScore).where(SupplierScore.supplier_id == user.supplier_id)
                      .order_by(SupplierScore.computed_at.desc()))
    open_pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.supplier_id == user.supplier_id,
                                                           PurchaseOrder.status.in_(PO.OPEN))).unique())
    rfqs = db.scalar(select(func.count()).select_from(RfqSupplier).join(Rfq, Rfq.id == RfqSupplier.rfq_id)
                     .where(RfqSupplier.supplier_id == user.supplier_id, Rfq.status == "OPEN",
                            RfqSupplier.responded_at.is_(None))) or 0
    return {
        "open_orders": len(open_pos),
        "awaiting_confirmation": sum(1 for p in open_pos if p.status == PO.SENT),
        "late": sum(1 for p in open_pos if is_late(p)),
        "total_orders": db.scalar(base) or 0,
        "rfqs_awaiting": rfqs,
        "score": None if not score else {"total": round(score.total_score, 1), "on_time_pct": round(score.on_time_pct, 1),
                                         "price": round(score.price_score, 1), "lead": round(score.lead_score, 1),
                                         "quality": round(score.quality_score, 1)},
    }


@router.get("/orders")
def orders(user: Supplier_, db: DB, p: Annotated[PageParams, Depends(page_params)], status: str | None = None) -> dict[str, Any]:
    stmt = select(PurchaseOrder).where(PurchaseOrder.supplier_id == user.supplier_id)
    if status == "open":
        stmt = stmt.where(PurchaseOrder.status.in_(PO.OPEN))
    elif status:
        stmt = stmt.where(PurchaseOrder.status == status)
    return paginate(db, stmt.order_by(PurchaseOrder.id.desc()), p, po_out)


@router.get("/orders/{po_id}")
def order(po_id: int, user: Supplier_, db: DB) -> dict[str, Any]:
    return detail(db, own_po(db, user, po_id))


@router.get("/orders/{po_id}/pdf")
def order_pdf(po_id: int, user: Supplier_, db: DB) -> Response:
    po = own_po(db, user, po_id)
    data = purchasing.stored_pdf(po) or purchasing.po_pdf(db, po)
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{po.po_no}.pdf"'})


@router.post("/orders/{po_id}/confirm")
def confirm(po_id: int, body: ConfirmIn, user: Supplier_, db: DB) -> dict[str, Any]:
    return detail(db, purchasing.supplier_confirm(db, own_po(db, user, po_id), user, body.eta, body.note))


@router.post("/orders/{po_id}/reject")
def reject(po_id: int, body: RejectIn, user: Supplier_, db: DB) -> dict[str, Any]:
    return detail(db, purchasing.supplier_reject(db, own_po(db, user, po_id), user, body.reason))


@router.post("/orders/{po_id}/dispatch")
def dispatch(po_id: int, body: DispatchIn, user: Supplier_, db: DB) -> dict[str, Any]:
    po = own_po(db, user, po_id)
    return detail(db, purchasing.supplier_dispatch(db, po, user, eta=body.eta, tracking_ref=body.tracking_ref,
                                                   courier_name=body.courier_name, note=body.note))


@router.post("/orders/{po_id}/invoice", status_code=201)
async def upload_invoice(po_id: int, user: Supplier_, db: DB, invoice_no: Annotated[str, Form()],
                         invoice_date: Annotated[date, Form()], lines: Annotated[str | None, Form()] = None,
                         file: Annotated[UploadFile | None, File()] = None) -> dict[str, Any]:
    """Invoice lines default to the PO quantities and prices; `lines` (JSON) overrides them."""
    po = own_po(db, user, po_id)
    path = None
    if file is not None and file.filename:
        content = await file.read()
        if len(content) > MAX_FILE:
            raise ValidationFailed("File is larger than 10 MB")
        safe = "".join(c for c in file.filename if c.isalnum() or c in "._-")[-80:]
        target = env.storage_subdir("invoices") / f"{po.po_no}_{safe}"
        target.write_bytes(content)
        path = str(target)
    try:
        parsed = json.loads(lines) if lines else [{"po_line_id": ln.id, "qty": ln.qty, "unit_price": ln.unit_price}
                                                   for ln in po.lines]
    except json.JSONDecodeError:
        raise ValidationFailed("lines must be valid JSON")
    inv = receiving.record_invoice(db, po, invoice_no=invoice_no, invoice_date=invoice_date, lines=parsed, user=user,
                                   source="portal", file_path=path)
    return {"invoice_id": inv.id, "status": inv.status, "order": detail(db, po)}


@router.get("/invoices")
def invoices(user: Supplier_, db: DB, p: Annotated[PageParams, Depends(page_params)]) -> dict[str, Any]:
    stmt = select(SupplierInvoice).where(SupplierInvoice.supplier_id == user.supplier_id).order_by(SupplierInvoice.id.desc())
    return paginate(db, stmt, p, lambda i: {"id": i.id, "invoice_no": i.invoice_no, "invoice_date": i.invoice_date,
                                            "po_id": i.po_id, "total": i.total, "status": i.status, "source": i.source})
