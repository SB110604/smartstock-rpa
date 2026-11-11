"""Purchase orders, goods receipts, supplier invoices and 3-way matches."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.deps import DB, require
from app.core.errors import NotFound
from app.core.pagination import PageParams, apply_sort, page_params, paginate
from app.core.timeutil import today
from app.models.catalog import Supplier
from app.models.core import User
from app.models.purchasing import (
    GoodsReceipt,
    OrderStatusHistory,
    PurchaseOrder,
    SupplierInvoice,
    SupplierReturn,
    ThreeWayMatch,
)
from app.services import documents
from app.services import settings as settings_svc
from app.workflow import purchasing, receiving
from app.workflow.machines import PO

router = APIRouter(tags=["purchase orders"])
Reader = Annotated[User, Depends(require("po.read"))]
Writer = Annotated[User, Depends(require("po.write"))]
Receiver = Annotated[User, Depends(require("grn.write"))]
InvoiceWriter = Annotated[User, Depends(require("invoice.write"))]
Resolver = Annotated[User, Depends(require("match.resolve"))]


class GrnLineIn(BaseModel):
    po_line_id: int
    received_qty: float = Field(0, ge=0)
    damaged_qty: float = Field(0, ge=0)
    batch_no: str | None = Field(None, max_length=60)
    expiry_date: date | None = None


class GrnIn(BaseModel):
    lines: list[GrnLineIn] = Field(min_length=1)
    note: str | None = Field(None, max_length=1000)


class InvoiceLineIn(BaseModel):
    po_line_id: int | None = None
    product_id: int | None = None
    description: str | None = None
    qty: float = Field(ge=0)
    unit_price: float = Field(ge=0)
    gst_rate: float | None = None


class InvoiceIn(BaseModel):
    invoice_no: str = Field(min_length=1, max_length=60)
    invoice_date: date
    lines: list[InvoiceLineIn] = Field(min_length=1)
    source: str = Field("manual", pattern="^(manual|ocr|portal)$")
    ocr_text: str | None = None


class NoteIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


class ReasonIn(BaseModel):
    reason: str | None = Field(None, max_length=1000)


def is_late(po: PurchaseOrder) -> bool:
    """Open POs: past the predicted/required date, or the supplier's ETA is after the required date (spec 7.6).
    Delivered POs: delivered after the required date."""
    if po.status in PO.OPEN:
        due = po.predicted_date or po.expected_date
        eta_late = bool(po.supplier_eta and po.expected_date and po.supplier_eta > po.expected_date)
        return bool(due and today() > due) or eta_late
    return bool(po.delivered_at and po.expected_date and po.delivered_at.date() > po.expected_date)


def po_out(po: PurchaseOrder) -> dict[str, Any]:
    return {
        "id": po.id, "po_no": po.po_no, "status": po.status, "supplier_id": po.supplier_id, "supplier": po.supplier.name,
        "location_id": po.location_id, "location": po.location.name, "order_date": po.order_date,
        "expected_date": po.expected_date, "predicted_date": po.predicted_date, "supplier_eta": po.supplier_eta,
        "is_interstate": po.is_interstate, "subtotal": po.subtotal, "cgst": po.cgst, "sgst": po.sgst, "igst": po.igst,
        "total": po.total, "sent_at": po.sent_at, "confirmed_at": po.confirmed_at, "dispatched_at": po.dispatched_at,
        "delivered_at": po.delivered_at, "closed_at": po.closed_at, "tracking_ref": po.tracking_ref,
        "courier_name": po.courier_name, "courier_status": po.courier_status, "rejection_reason": po.rejection_reason,
        "late": is_late(po), "lines_count": len(po.lines),
    }


def line_out(ln: Any) -> dict[str, Any]:
    return {"id": ln.id, "product_id": ln.product_id, "product": ln.product.name, "sku": ln.product.sku,
            "unit": ln.product.unit, "is_perishable": ln.product.is_perishable, "shelf_life_days": ln.product.shelf_life_days,
            "hsn_code": ln.hsn_code, "qty": ln.qty, "unit_price": ln.unit_price, "gst_rate": ln.gst_rate,
            "received_qty": ln.received_qty, "damaged_qty": ln.damaged_qty,
            "remaining": round(ln.qty - ln.received_qty - ln.damaged_qty, 3),
            "purchase_request_id": ln.purchase_request_id}


def po_detail(db: DB, po: PurchaseOrder) -> dict[str, Any]:
    history = db.scalars(select(OrderStatusHistory).where(OrderStatusHistory.po_id == po.id).order_by(OrderStatusHistory.id))
    grns = db.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id).order_by(GoodsReceipt.id))
    invoices = db.scalars(select(SupplierInvoice).where(SupplierInvoice.po_id == po.id).order_by(SupplierInvoice.id))
    matches = db.scalars(select(ThreeWayMatch).where(ThreeWayMatch.po_id == po.id).order_by(ThreeWayMatch.id.desc()))
    rets = db.scalars(select(SupplierReturn).where(SupplierReturn.po_id == po.id))
    return {
        **po_out(po),
        "supplier_detail": {"gstin": po.supplier.gstin, "state": po.supplier.state, "email": po.supplier.email,
                            "phone": po.supplier.phone},
        "lines": [line_out(ln) for ln in po.lines],
        "timeline": [{"from": h.from_status, "to": h.to_status, "note": h.note, "actor_type": h.actor_type,
                      "at": h.created_at} for h in history],
        "grns": [{"id": g.id, "grn_no": g.grn_no, "received_at": g.received_at, "note": g.note,
                  "lines": [{"product": gl.product.name, "received_qty": gl.received_qty, "damaged_qty": gl.damaged_qty,
                             "batch_no": gl.batch_no, "expiry_date": gl.expiry_date} for gl in g.lines]}
                 for g in grns.unique()],
        "invoices": [{"id": i.id, "invoice_no": i.invoice_no, "invoice_date": i.invoice_date, "total": i.total,
                      "tax": i.tax, "status": i.status, "source": i.source,
                      "lines": [{"po_line_id": il.po_line_id, "description": il.description, "qty": il.qty,
                                 "unit_price": il.unit_price, "gst_rate": il.gst_rate} for il in i.lines]}
                     for i in invoices.unique()],
        "matches": [{"id": m.id, "invoice_id": m.invoice_id, "status": m.status, "details": m.details_json,
                     "resolution_note": m.resolution_note, "resolved_at": m.resolved_at, "created_at": m.created_at}
                    for m in matches],
        "returns": [{"id": r.id, "return_no": r.return_no, "status": r.status, "total": r.total} for r in rets.unique()],
    }


@router.get("/purchase-orders")
def list_pos(user: Reader, db: DB, p: Annotated[PageParams, Depends(page_params)], status: str | None = None,
             supplier_id: int | None = None, q: str | None = None, late: bool | None = None,
             receivable: bool = False) -> dict[str, Any]:
    stmt = select(PurchaseOrder).join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status.in_(status.split(",")))
    if receivable:
        stmt = stmt.where(PurchaseOrder.status.in_(PO.RECEIVABLE))
    if supplier_id:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if q:
        stmt = stmt.where(or_(PurchaseOrder.po_no.ilike(f"%{q}%"), Supplier.name.ilike(f"%{q}%")))
    stmt = apply_sort(stmt, p.sort, {"order_date": PurchaseOrder.order_date, "total": PurchaseOrder.total,
                                     "expected_date": PurchaseOrder.expected_date},
                      PurchaseOrder.id.desc())
    if late is not None:
        rows = [po for po in db.scalars(stmt.where(PurchaseOrder.status.in_(PO.OPEN))).unique() if is_late(po) == late]
        start = (p.page - 1) * p.page_size
        return {"items": [po_out(r) for r in rows[start:start + p.page_size]], "total": len(rows), "page": p.page,
                "page_size": p.page_size}
    return paginate(db, stmt, p, po_out)


@router.get("/purchase-orders/{po_id}")
def get_po(po_id: int, user: Reader, db: DB) -> dict[str, Any]:
    return po_detail(db, purchasing.get_po(db, po_id))


@router.get("/purchase-orders/{po_id}/pdf")
def po_pdf(po_id: int, user: Reader, db: DB) -> Response:
    po = purchasing.get_po(db, po_id)
    data = purchasing.stored_pdf(po) or purchasing.po_pdf(db, po)
    db.commit()
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{po.po_no}.pdf"'})


@router.post("/purchase-orders/{po_id}/send")
def resend(po_id: int, user: Writer, db: DB) -> dict[str, Any]:
    po = purchasing.get_po(db, po_id)
    purchasing.send_po(db, po, user, resend=po.status != PO.CREATED)
    db.commit()
    return po_detail(db, po)


@router.post("/purchase-orders/{po_id}/cancel")
def cancel(po_id: int, body: ReasonIn, user: Writer, db: DB) -> dict[str, Any]:
    return po_detail(db, purchasing.cancel_po(db, purchasing.get_po(db, po_id), user, body.reason))


@router.post("/purchase-orders/from-approved")
def from_approved(user: Writer, db: DB) -> dict[str, Any]:
    pos = purchasing.create_purchase_orders(db, actor=user)
    db.commit()
    return {"created": [p.po_no for p in pos]}


@router.post("/purchase-orders/{po_id}/grn", status_code=201)
def receive(po_id: int, body: GrnIn, user: Receiver, db: DB) -> dict[str, Any]:
    po = purchasing.get_po(db, po_id)
    grn = receiving.receive(db, po, [ln.model_dump() for ln in body.lines], user, body.note)
    return {"grn_id": grn.id, "grn_no": grn.grn_no, "po": po_detail(db, po)}


@router.get("/goods-receipts/{grn_id}/pdf")
def grn_pdf(grn_id: int, user: Reader, db: DB) -> Response:
    grn = db.get(GoodsReceipt, grn_id)
    if not grn:
        raise NotFound("Goods receipt not found")
    po = purchasing.get_po(db, grn.po_id)
    data = documents.grn_pdf(grn, po, settings_svc.get(db, "business"))
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{grn.grn_no}.pdf"'})


@router.post("/purchase-orders/{po_id}/invoices", status_code=201)
def add_invoice(po_id: int, body: InvoiceIn, user: InvoiceWriter, db: DB) -> dict[str, Any]:
    po = purchasing.get_po(db, po_id)
    inv = receiving.record_invoice(db, po, invoice_no=body.invoice_no, invoice_date=body.invoice_date,
                                   lines=[ln.model_dump() for ln in body.lines], user=user, source=body.source,
                                   ocr_text=body.ocr_text)
    return {"invoice_id": inv.id, "status": inv.status, "po": po_detail(db, po)}


@router.post("/matches/{match_id}/resolve")
def resolve(match_id: int, body: NoteIn, user: Resolver, db: DB) -> dict[str, Any]:
    m = db.get(ThreeWayMatch, match_id)
    if not m:
        raise NotFound("Match result not found")
    receiving.resolve_mismatch(db, m, user, body.note)
    return po_detail(db, purchasing.get_po(db, m.po_id))


@router.post("/purchase-orders/{po_id}/close")
def close(po_id: int, user: Writer, db: DB) -> dict[str, Any]:
    po = purchasing.get_po(db, po_id)
    receiving.close(db, po, user, note="Closed manually")
    db.commit()
    return po_detail(db, po)
