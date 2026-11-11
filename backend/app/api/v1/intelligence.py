"""Chat assistant, invoice OCR, what-if simulator, RFQs (manager + supplier portal) and email-quote review."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import llm
from app.assistant import engine
from app.core.config import settings as env
from app.core.deps import DB, CurrentUser, require
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.pagination import PageParams, page_params, paginate
from app.models.core import User
from app.models.purchasing import Rfq, RfqSupplier, SupplierQuote
from app.services import ocr, quote_reader, simulator
from app.workflow import rfqs

router = APIRouter(tags=["intelligence"])
Chatter = Annotated[User, Depends(require("chat.use"))]
InvoiceWriter = Annotated[User, Depends(require("invoice.write"))]
Simulator = Annotated[User, Depends(require("simulator.use"))]
RfqMgr = Annotated[User, Depends(require("rfq.manage"))]
Portal = Annotated[User, Depends(require("portal.use"))]
MAX_FILE = 10 * 1024 * 1024


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


@router.post("/assistant/chat")
def chat(body: ChatIn, user: Chatter, db: DB) -> dict[str, Any]:
    a = engine.answer(db, user, body.message)
    return {"reply": a.reply, "mode": a.mode, "tool_calls": a.tool_calls}


@router.get("/assistant/history")
def chat_history(user: Chatter, db: DB) -> list[dict[str, Any]]:
    return [{"id": m.id, "role": m.role, "content": m.content, "tool_calls": m.tool_calls_json, "created_at": m.created_at}
            for m in engine.history(db, user)]


@router.delete("/assistant/history")
def chat_clear(user: Chatter, db: DB) -> dict[str, str]:
    engine.clear(db, user)
    return {"detail": "Conversation cleared"}


@router.get("/assistant/status")
def assistant_status(user: CurrentUser) -> dict[str, Any]:
    return {"llm": llm.status(), "ocr": ocr.available(), "imap": env.imap_enabled}


# ---------------------------------------------------------------- OCR

@router.post("/ocr/invoice")
async def scan_invoice(user: InvoiceWriter, db: DB, file: Annotated[UploadFile, File()],
                       po_id: Annotated[int | None, Form()] = None) -> dict[str, Any]:
    """Returns a pre-filled invoice for the user to confirm — nothing is saved here."""
    content = await file.read()
    if len(content) > MAX_FILE:
        raise ValidationFailed("File is larger than 10 MB")
    return ocr.scan_invoice(db, content, file.filename or "invoice.png", po_id)


# ---------------------------------------------------------------- simulator

class SimIn(BaseModel):
    demand_change_pct: float = Field(0, ge=-90, le=500)
    lead_time_change_days: float = Field(0, ge=-30, le=60)
    unavailable_supplier_id: int | None = None
    service_level: float | None = Field(None, ge=0.5, le=0.999)
    category_id: int | None = None
    product_ids: list[int] | None = None


@router.post("/simulator")
def simulate(body: SimIn, user: Simulator, db: DB) -> dict[str, Any]:
    return simulator.simulate(db, **body.model_dump())


# ---------------------------------------------------------------- RFQs (manager)

class RfqItemIn(BaseModel):
    product_id: int
    qty: float = Field(gt=0)


class RfqIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    items: list[RfqItemIn] = Field(min_length=1)
    supplier_ids: list[int] = Field(min_length=1)
    due_date: date | None = None
    note: str | None = None


def rfq_out(r: Rfq) -> dict[str, Any]:
    return {"id": r.id, "rfq_no": r.rfq_no, "title": r.title, "status": r.status, "due_date": r.due_date, "note": r.note,
            "created_at": r.created_at,
            "items": [{"id": i.id, "product_id": i.product_id, "product": i.product.name, "qty": i.qty, "unit": i.product.unit}
                      for i in r.items],
            "suppliers": [{"supplier_id": s.supplier_id, "name": s.supplier.name, "responded_at": s.responded_at}
                          for s in r.suppliers]}


@router.get("/rfqs")
def list_rfqs(user: RfqMgr, db: DB, p: Annotated[PageParams, Depends(page_params)], status: str | None = None) -> dict[str, Any]:
    stmt = select(Rfq)
    if status:
        stmt = stmt.where(Rfq.status == status)
    return paginate(db, stmt.order_by(Rfq.id.desc()), p, rfq_out)


@router.post("/rfqs", status_code=201)
def create_rfq(body: RfqIn, user: RfqMgr, db: DB) -> dict[str, Any]:
    r = rfqs.create(db, title=body.title, items=[i.model_dump() for i in body.items], supplier_ids=body.supplier_ids,
                    due_date=body.due_date, note=body.note, user=user)
    return rfq_out(r)


@router.get("/rfqs/{rfq_id}")
def get_rfq(rfq_id: int, user: RfqMgr, db: DB) -> dict[str, Any]:
    r = rfqs.get(db, rfq_id)
    return {**rfq_out(r), "comparison": rfqs.comparison(db, r)}


@router.post("/rfqs/{rfq_id}/close")
def close_rfq(rfq_id: int, user: RfqMgr, db: DB, cancel: bool = False) -> dict[str, Any]:
    r = rfqs.close(db, rfqs.get(db, rfq_id), user, "CANCELLED" if cancel else "CLOSED")
    return {**rfq_out(r), "comparison": rfqs.comparison(db, r)}


def _quote(db: DB, quote_id: int) -> SupplierQuote:
    q = db.get(SupplierQuote, quote_id)
    if not q:
        raise NotFound("Quote not found")
    return q


@router.post("/quotes/{quote_id}/use")
def use_quote(quote_id: int, user: RfqMgr, db: DB) -> dict[str, Any]:
    q = rfqs.use_quote(db, _quote(db, quote_id), user)
    return {"id": q.id, "status": q.status}


@router.post("/quotes/{quote_id}/reject")
def reject_quote(quote_id: int, user: RfqMgr, db: DB) -> dict[str, Any]:
    q = rfqs.reject_quote(db, _quote(db, quote_id), user)
    return {"id": q.id, "status": q.status}


@router.get("/quotes/pending")
def pending_email_quotes(user: RfqMgr, db: DB) -> dict[str, Any]:
    rows = db.scalars(select(SupplierQuote).where(SupplierQuote.status == "pending_review").order_by(SupplierQuote.id.desc()))
    return {"enabled": env.imap_enabled, "items": [{"id": q.id, "supplier": q.supplier.name, "product": q.product.name,
                                                    "unit_price": q.unit_price, "lead_time_days": q.lead_time_days,
                                                    "note": q.note, "created_at": q.created_at} for q in rows.unique()]}


@router.post("/quotes/fetch-email")
def fetch_email_quotes(user: RfqMgr, db: DB) -> dict[str, Any]:
    if not env.imap_enabled:
        raise ValidationFailed("Email quotation reader is not configured (IMAP settings missing)")
    return quote_reader.fetch(db)


# ---------------------------------------------------------------- RFQs (supplier portal)

class QuoteLineIn(BaseModel):
    rfq_item_id: int
    unit_price: float = Field(gt=0)
    lead_time_days: int | None = Field(None, ge=0, le=180)
    min_order_qty: float | None = Field(None, gt=0)
    valid_till: date | None = None
    note: str | None = Field(None, max_length=300)


class QuotesIn(BaseModel):
    quotes: list[QuoteLineIn] = Field(min_length=1)


def _portal_rfq(db: DB, user: User, rfq_id: int) -> Rfq:
    r = db.get(Rfq, rfq_id)
    if not r or not any(s.supplier_id == user.supplier_id for s in r.suppliers):
        raise Forbidden("This RFQ was not sent to your company")
    return r


def _portal_out(db: DB, r: Rfq, user: User) -> dict[str, Any]:
    mine = {q.rfq_item_id: q for q in db.scalars(select(SupplierQuote).where(SupplierQuote.rfq_id == r.id,
                                                                            SupplierQuote.supplier_id == user.supplier_id))}
    inv = next(s for s in r.suppliers if s.supplier_id == user.supplier_id)
    return {"id": r.id, "rfq_no": r.rfq_no, "title": r.title, "status": r.status, "due_date": r.due_date, "note": r.note,
            "responded_at": inv.responded_at,
            "items": [{"id": i.id, "product": i.product.name, "qty": i.qty, "unit": i.product.unit,
                       "my_quote": None if i.id not in mine else {"unit_price": mine[i.id].unit_price,
                                                                  "lead_time_days": mine[i.id].lead_time_days,
                                                                  "status": mine[i.id].status}} for i in r.items]}


@router.get("/portal/rfqs")
def portal_rfqs(user: Portal, db: DB) -> list[dict[str, Any]]:
    rows = db.scalars(select(Rfq).join(RfqSupplier, RfqSupplier.rfq_id == Rfq.id)
                      .where(RfqSupplier.supplier_id == user.supplier_id).order_by(Rfq.id.desc())).unique()
    return [_portal_out(db, r, user) for r in rows]


@router.get("/portal/rfqs/{rfq_id}")
def portal_rfq(rfq_id: int, user: Portal, db: DB) -> dict[str, Any]:
    return _portal_out(db, _portal_rfq(db, user, rfq_id), user)


@router.post("/portal/rfqs/{rfq_id}/quotes")
def portal_quote(rfq_id: int, body: QuotesIn, user: Portal, db: DB) -> dict[str, Any]:
    r = rfqs.submit_quotes(db, _portal_rfq(db, user, rfq_id), user, [q.model_dump() for q in body.quotes])
    return _portal_out(db, r, user)
