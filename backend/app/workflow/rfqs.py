"""RFQs (spec 7.4): create → email suppliers with portal link → quotes in portal → compare → use a quote."""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.timeutil import now
from app.models.catalog import Supplier, SupplierProduct
from app.models.core import Role, User
from app.models.purchasing import Rfq, RfqItem, RfqSupplier, SupplierQuote
from app.services import audit, mailer, notify, numbering, stock
from app.services import settings as settings_svc
from app.workflow.engine import record_initial, transition
from app.workflow.machines import RFQ
from app.workflow.machines import rfq as rfq_machine


def create(db: Session, *, title: str, items: list[dict[str, Any]], supplier_ids: list[int], due_date: date | None,
           note: str | None, user: User) -> Rfq:
    if not items or not supplier_ids:
        raise ValidationFailed("Add at least one product and one supplier")
    r = Rfq(rfq_no=numbering.next_number(db, Rfq.rfq_no, "RFQ"), title=title, due_date=due_date, note=note,
            created_by=user.id, status=RFQ.OPEN)
    for it in items:
        p = stock.get_product(db, int(it["product_id"]))
        if float(it["qty"]) <= 0:
            raise ValidationFailed("Quantities must be greater than zero")
        r.items.append(RfqItem(product_id=p.id, qty=float(it["qty"])))
    sups = []
    for sid in dict.fromkeys(supplier_ids):
        s = db.get(Supplier, sid)
        if not s:
            raise NotFound(f"Supplier {sid} not found")
        r.suppliers.append(RfqSupplier(supplier_id=sid, invited_at=now()))
        sups.append(s)
    db.add(r)
    db.flush()
    record_initial(db, rfq_machine, r, actor=user)
    audit.created(db, user, r, "rfq")
    business = settings_svc.get(db, "business")["name"]
    rows = "".join(f"<li>{i.product.name} — {i.qty:g} {i.product.unit}</li>" for i in r.items)
    for s in sups:
        if s.email:
            mailer.send_email(s.email, f"Request for quotation {r.rfq_no} from {business}", mailer.layout(
                f"Request for quotation {r.rfq_no}",
                f"<p>{title}</p><ul>{rows}</ul><p>Please quote your best price and lead time"
                + (f" by {due_date:%d-%m-%Y}" if due_date else "") + ".</p>"
                + mailer.button(f"{env.FRONTEND_URL}/portal/rfqs/{r.id}", "Submit quotation"), business))
        users = list(db.scalars(select(User).where(User.supplier_id == s.id, User.is_active.is_(True))))
        if users:
            notify.notify(db, users, f"New RFQ {r.rfq_no}", title, link=f"/portal/rfqs/{r.id}", channels={"in_app"})
    db.commit()
    return r


def get(db: Session, rfq_id: int) -> Rfq:
    r = db.get(Rfq, rfq_id)
    if not r:
        raise NotFound("RFQ not found")
    return r


def submit_quotes(db: Session, r: Rfq, user: User, quotes: list[dict[str, Any]]) -> Rfq:
    inv = next((s for s in r.suppliers if s.supplier_id == user.supplier_id), None)
    if inv is None:
        raise Forbidden("Your company was not invited to this RFQ")
    if r.status != RFQ.OPEN:
        raise Conflict("This RFQ is no longer accepting quotations", code="invalid_transition")
    items = {i.id: i for i in r.items}
    for q in quotes:
        item = items.get(int(q["rfq_item_id"]))
        if not item:
            raise NotFound("RFQ item not found")
        if float(q["unit_price"]) <= 0:
            raise ValidationFailed("Prices must be greater than zero")
        existing = db.scalar(select(SupplierQuote).where(SupplierQuote.rfq_item_id == item.id,
                                                         SupplierQuote.supplier_id == user.supplier_id))
        if existing:
            existing.unit_price, existing.lead_time_days = float(q["unit_price"]), q.get("lead_time_days")
            existing.min_order_qty, existing.valid_till, existing.note = q.get("min_order_qty"), q.get("valid_till"), q.get("note")
        else:
            db.add(SupplierQuote(rfq_id=r.id, rfq_item_id=item.id, supplier_id=user.supplier_id or 0, product_id=item.product_id,
                                 unit_price=float(q["unit_price"]), lead_time_days=q.get("lead_time_days"),
                                 min_order_qty=q.get("min_order_qty"), valid_till=q.get("valid_till"), note=q.get("note"),
                                 status="submitted", source="portal"))
    inv.responded_at = now()
    audit.record(db, user, "quote", "rfq", r.id, None, {"supplier_id": user.supplier_id, "lines": len(quotes)})
    notify.notify_roles(db, [Role.MANAGER], f"Quotation received for {r.rfq_no}", inv.supplier.name, link=f"/rfqs/{r.id}",
                        channels={"in_app"})
    db.commit()
    return r


def comparison(db: Session, r: Rfq) -> list[dict[str, Any]]:
    out = []
    for item in r.items:
        quotes = list(db.scalars(select(SupplierQuote).where(SupplierQuote.rfq_item_id == item.id)
                                 .order_by(SupplierQuote.unit_price)).unique())
        current = db.scalars(select(SupplierProduct).where(SupplierProduct.product_id == item.product_id)).unique()
        best_current = min((sp.unit_price for sp in current), default=None)
        out.append({"item_id": item.id, "product_id": item.product_id, "product": item.product.name, "qty": item.qty,
                    "unit": item.product.unit, "current_best_price": best_current,
                    "quotes": [{"id": q.id, "supplier_id": q.supplier_id, "supplier": q.supplier.name, "unit_price": q.unit_price,
                                "lead_time_days": q.lead_time_days, "min_order_qty": q.min_order_qty, "valid_till": q.valid_till,
                                "status": q.status, "note": q.note, "total": round(q.unit_price * item.qty, 2),
                                "saving_pct": round((best_current - q.unit_price) / best_current * 100, 1) if best_current else None}
                               for q in quotes]})
    return out


def use_quote(db: Session, quote: SupplierQuote, user: User) -> SupplierQuote:
    """Accept a quote: the supplier's price/lead for that product is updated (spec: 'Use this quote')."""
    if quote.status == "accepted":
        raise Conflict("Quote already used")
    sp = db.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == quote.supplier_id,
                                                 SupplierProduct.product_id == quote.product_id))
    values = {"unit_price": quote.unit_price, "lead_time_days": quote.lead_time_days or (sp.lead_time_days if sp else 3),
              "min_order_qty": quote.min_order_qty or (sp.min_order_qty if sp else 1), "valid_till": quote.valid_till}
    if sp:
        audit.apply_update(db, user, sp, values)
    else:
        sp = SupplierProduct(supplier_id=quote.supplier_id, product_id=quote.product_id, **values)
        db.add(sp)
        audit.created(db, user, sp)
    for other in db.scalars(select(SupplierQuote).where(SupplierQuote.rfq_item_id == quote.rfq_item_id,
                                                        SupplierQuote.id != quote.id, SupplierQuote.rfq_item_id.is_not(None))):
        if other.status in ("submitted", "pending_review"):
            other.status = "rejected"
    quote.status = "accepted"
    db.flush()
    if quote.rfq_id:
        r = get(db, quote.rfq_id)
        awarded = {q.rfq_item_id for q in db.scalars(select(SupplierQuote).where(SupplierQuote.rfq_id == r.id,
                                                                                  SupplierQuote.status == "accepted"))}
        if r.status in (RFQ.OPEN, RFQ.CLOSED) and all(i.id in awarded for i in r.items):
            transition(db, rfq_machine, r, RFQ.AWARDED, actor=user, note="All items awarded")
    db.commit()
    return quote


def reject_quote(db: Session, quote: SupplierQuote, user: User) -> SupplierQuote:
    quote.status = "rejected"
    audit.record(db, user, "reject_quote", "supplier_quote", quote.id)
    db.commit()
    return quote


def close(db: Session, r: Rfq, user: User, status: str) -> Rfq:
    transition(db, rfq_machine, r, status, actor=user)
    db.commit()
    return r
