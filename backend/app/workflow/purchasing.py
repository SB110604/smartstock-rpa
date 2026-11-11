"""Purchase requests → purchase orders → supplier actions (spec 7.5, 8.2)."""

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import now, today
from app.models.catalog import Supplier, SupplierProduct
from app.models.core import Role, User
from app.models.purchasing import PoLine, PurchaseOrder, PurchaseRequest
from app.services import audit, documents, gst, mailer, notify, numbering, stock
from app.services import settings as settings_svc
from app.services.pdfbase import inr
from app.workflow import approvals
from app.workflow.engine import record_initial, transition
from app.workflow.machines import PO, PR, purchase_order, purchase_request

# ------------------------------------------------------------------ purchase requests

def price_for(db: Session, product_id: int, supplier_id: int | None) -> tuple[float, int]:
    if supplier_id:
        sp = db.scalar(select(SupplierProduct).where(SupplierProduct.product_id == product_id,
                                                     SupplierProduct.supplier_id == supplier_id))
        if sp:
            return sp.unit_price, sp.lead_time_days
    product = stock.get_product(db, product_id)
    return product.cost_price, 3


def create_request(
    db: Session,
    *,
    product_id: int,
    location_id: int,
    qty: float,
    supplier_id: int | None,
    user: User | None,
    created_by: str = "user",
    reason_text: str | None = None,
    reason_json: dict[str, Any] | None = None,
    submit: bool = True,
) -> PurchaseRequest:
    if qty <= 0:
        raise ValidationFailed("Quantity must be greater than zero")
    product = stock.get_product(db, product_id)
    stock.check_location(db, location_id)
    if supplier_id is None:
        cheapest = db.scalar(select(SupplierProduct).where(SupplierProduct.product_id == product_id)
                             .order_by(SupplierProduct.unit_price))
        supplier_id = cheapest.supplier_id if cheapest else None
    if supplier_id and not db.get(Supplier, supplier_id):
        raise NotFound("Supplier not found")
    price, _ = price_for(db, product_id, supplier_id)
    pr = PurchaseRequest(product_id=product.id, location_id=location_id, suggested_qty=qty, suggested_supplier_id=supplier_id,
                         est_unit_price=price, est_total=round(price * qty, 2), reason_text=reason_text,
                         reason_json=reason_json, created_by=created_by,
                         created_by_user_id=user.id if user else None, status=PR.DRAFT)
    db.add(pr)
    db.flush()
    record_initial(db, purchase_request, pr, actor=user, actor_type=None if user else "agent")
    audit.created(db, user, pr, "purchase_request")
    if submit:
        approvals.submit(db, pr, user, actor_type=None if user else "agent")
    return pr


def cancel_request(db: Session, pr: PurchaseRequest, user: User, reason: str | None) -> PurchaseRequest:
    transition(db, purchase_request, pr, PR.CANCELLED, actor=user, note=reason)
    for a in pr.approvals:
        if a.decision == "pending":
            a.decision = "skipped"
    db.commit()
    return pr


# ------------------------------------------------------------------ purchase orders

def create_purchase_orders(db: Session, actor: User | None, pr_ids: list[int] | None = None,
                           send: bool = True) -> list[PurchaseOrder]:
    """Group APPROVED requests (without a PO) by supplier and location into one PO each, then send them."""
    stmt = select(PurchaseRequest).where(PurchaseRequest.status == PR.APPROVED, PurchaseRequest.po_id.is_(None))
    if pr_ids is not None:
        stmt = stmt.where(PurchaseRequest.id.in_(pr_ids))
    groups: dict[tuple[int, int], list[PurchaseRequest]] = defaultdict(list)
    for pr in db.scalars(stmt.order_by(PurchaseRequest.id)).unique():
        sup = pr.final_supplier_id or pr.suggested_supplier_id
        if not sup:
            continue
        groups[(sup, pr.location_id)].append(pr)
    business = settings_svc.get(db, "business")
    created: list[PurchaseOrder] = []
    for (sup_id, loc_id), prs in groups.items():
        supplier = db.get(Supplier, sup_id)
        assert supplier is not None
        lead = max(price_for(db, pr.product_id, sup_id)[1] for pr in prs)
        po = PurchaseOrder(po_no=numbering.next_number(db, PurchaseOrder.po_no, "PO"), supplier_id=sup_id,
                           location_id=loc_id, status=PO.CREATED, order_date=today(),
                           expected_date=today() + timedelta(days=lead), predicted_date=today() + timedelta(days=lead),
                           is_interstate=gst.is_interstate(business.get("state"), supplier.state),
                           created_by=actor.id if actor else None)
        for pr in prs:
            qty = pr.final_qty if pr.final_qty is not None else pr.suggested_qty
            product = pr.product
            po.lines.append(PoLine(product_id=pr.product_id, purchase_request_id=pr.id, qty=qty,
                                   unit_price=pr.est_unit_price, gst_rate=product.gst_rate, hsn_code=product.hsn_code))
        recalc(po)
        db.add(po)
        db.flush()
        record_initial(db, purchase_order, po, actor=actor, actor_type=None if actor else "agent",
                       note=f"From purchase request(s) {', '.join('#' + str(p.id) for p in prs)}")
        audit.created(db, actor, po, "purchase_order")
        for pr in prs:
            pr.po_id = po.id
            transition(db, purchase_request, pr, PR.ORDERED, actor=actor, actor_type=None if actor else "agent",
                       note=f"Ordered on {po.po_no}")
        created.append(po)
        if send:
            send_po(db, po, actor)
    db.flush()
    return created


def recalc(po: PurchaseOrder) -> None:
    t = gst.totals([(ln.qty, ln.unit_price, ln.gst_rate) for ln in po.lines], po.is_interstate)
    po.subtotal, po.cgst, po.sgst, po.igst, po.total = t.subtotal, t.cgst, t.sgst, t.igst, t.total


def get_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.get(PurchaseOrder, po_id)
    if not po:
        raise NotFound("Purchase order not found")
    return po


def po_pdf(db: Session, po: PurchaseOrder) -> bytes:
    data = documents.purchase_order_pdf(po, settings_svc.get(db, "business"), settings_svc.get(db, "po_terms"))
    po.pdf_path = documents.save("po", po.po_no, data)
    return data


def send_po(db: Session, po: PurchaseOrder, actor: User | None, resend: bool = False) -> PurchaseOrder:
    """Generate the PO PDF and email it to the supplier with the portal link (CREATED → SENT)."""
    data = po_pdf(db, po)
    business = settings_svc.get(db, "business")
    portal = f"{env.FRONTEND_URL}/portal/orders/{po.id}"
    lines = "".join(f"<li>{ln.product.name} — {ln.qty:g} {ln.product.unit} @ {inr(ln.unit_price)}</li>" for ln in po.lines)
    html = mailer.layout(
        f"Purchase order {po.po_no}{' (resent)' if resend else ''}",
        f"<p>Dear {po.supplier.contact_name or po.supplier.name},</p>"
        f"<p>Please find attached purchase order <b>{po.po_no}</b> dated {po.order_date:%d-%m-%Y} for "
        f"<b>{inr(po.total)}</b>, required by <b>{po.expected_date:%d-%m-%Y}</b> at {po.location.name}.</p>"
        f"<ul>{lines}</ul><p>Please confirm the order and share dispatch details and ETA in the supplier portal.</p>"
        f"{mailer.button(portal, 'Open supplier portal')}",
        business["name"],
    )
    if po.supplier.email:
        mailer.send_email(po.supplier.email, f"Purchase order {po.po_no} from {business['name']}", html,
                          text=f"PO {po.po_no}: {portal}", attachments=[(f"{po.po_no}.pdf", data, "application/pdf")])
    if po.status == PO.CREATED:
        transition(db, purchase_order, po, PO.SENT, actor=actor, actor_type=None if actor else "agent",
                   note=f"Emailed to {po.supplier.email or 'supplier (no email on file)'}")
    po.sent_at = now()
    if resend:
        audit.record(db, actor, "resend", "purchase_order", po.id, None, {"to": po.supplier.email})
    _notify_supplier_users(db, po, f"New purchase order {po.po_no}" if not resend else f"PO {po.po_no} resent",
                           f"{inr(po.total)} · required by {po.expected_date:%d-%m-%Y}")
    return po


def _notify_supplier_users(db: Session, po: PurchaseOrder, title: str, body: str) -> None:
    users = list(db.scalars(select(User).where(User.supplier_id == po.supplier_id, User.is_active.is_(True))))
    if users:
        notify.notify(db, users, title, body, link=f"/portal/orders/{po.id}", channels={"in_app"})


def _notify_managers(db: Session, po: PurchaseOrder, title: str, body: str) -> None:
    notify.notify_roles(db, [Role.MANAGER], title, body, link=f"/orders/{po.id}", channels={"in_app"})


def cancel_po(db: Session, po: PurchaseOrder, user: User, reason: str | None) -> PurchaseOrder:
    if not reason:
        raise ValidationFailed("A reason is required to cancel a PO")
    transition(db, purchase_order, po, PO.CANCELLED, actor=user, note=reason)
    _notify_supplier_users(db, po, f"PO {po.po_no} cancelled", reason)
    if po.supplier.email:
        mailer.send_email(po.supplier.email, f"Cancelled: purchase order {po.po_no}",
                          mailer.layout(f"PO {po.po_no} cancelled", f"<p>Reason: {reason}</p>"))
    db.commit()
    return po


# ------------------------------------------------------------------ supplier actions (portal)

def supplier_confirm(db: Session, po: PurchaseOrder, user: User, eta: date | None, note: str | None) -> PurchaseOrder:
    transition(db, purchase_order, po, PO.CONFIRMED, actor=user, actor_type="supplier", note=note)
    po.confirmed_at = now()
    if eta:
        po.supplier_eta = eta
    _notify_managers(db, po, f"{po.supplier.name} confirmed {po.po_no}",
                     f"ETA {eta:%d-%m-%Y}" if eta else "Order confirmed")
    db.commit()
    return po


def supplier_reject(db: Session, po: PurchaseOrder, user: User, reason: str) -> PurchaseOrder:
    if not reason or not reason.strip():
        raise ValidationFailed("Please give a reason")
    transition(db, purchase_order, po, PO.REJECTED, actor=user, actor_type="supplier", note=reason)
    po.rejection_reason = reason
    notify.notify_roles(db, [Role.MANAGER], f"{po.supplier.name} rejected {po.po_no}", reason, link=f"/orders/{po.id}")
    db.commit()
    return po


def supplier_dispatch(db: Session, po: PurchaseOrder, user: User, *, eta: date, tracking_ref: str | None,
                      courier_name: str | None, note: str | None) -> PurchaseOrder:
    if po.status == PO.SENT:  # dispatch implies confirmation
        supplier_confirm(db, po, user, eta, "Confirmed at dispatch")
    transition(db, purchase_order, po, PO.DISPATCHED, actor=user, actor_type="supplier",
               note=note or f"ETA {eta:%d-%m-%Y}")
    po.dispatched_at, po.supplier_eta, po.tracking_ref, po.courier_name = now(), eta, tracking_ref, courier_name
    po.courier_status = "Dispatched"
    _notify_managers(db, po, f"{po.po_no} dispatched", f"ETA {eta:%d-%m-%Y}" + (f" · {tracking_ref}" if tracking_ref else ""))
    db.commit()
    return po


def stored_pdf(po: PurchaseOrder) -> bytes | None:
    if po.pdf_path and Path(po.pdf_path).exists():
        return Path(po.pdf_path).read_bytes()
    return None
