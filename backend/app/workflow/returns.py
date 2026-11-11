"""Supplier returns (spec 8.5): request → approval → debit-note PDF → return_out movement → credit note."""

from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.models.catalog import Supplier
from app.models.core import Role, User
from app.models.inventory import Batch, MovementType
from app.models.purchasing import SupplierReturn, SupplierReturnLine
from app.services import audit, documents, gst, mailer, notify, numbering, stock
from app.services import settings as settings_svc
from app.workflow.engine import record_initial, transition
from app.workflow.machines import RET, supplier_return


def create(db: Session, *, supplier_id: int, location_id: int, lines: list[dict[str, Any]], reason: str | None,
           user: User | None, po_id: int | None = None) -> SupplierReturn:
    supplier = db.get(Supplier, supplier_id)
    if not supplier:
        raise NotFound("Supplier not found")
    if not lines:
        raise ValidationFailed("Add at least one batch to return")
    ret = SupplierReturn(return_no=numbering.next_number(db, SupplierReturn.return_no, "RET"), supplier_id=supplier_id,
                         po_id=po_id, location_id=location_id, status=RET.DRAFT, reason=reason,
                         created_by=user.id if user else None)
    calc = []
    for e in lines:
        batch = db.get(Batch, int(e["batch_id"]))
        if not batch or batch.location_id != location_id:
            raise NotFound("Batch not found at this location")
        qty = float(e["qty"])
        if qty <= 0 or qty > batch.qty_on_hand + 1e-9:
            raise ValidationFailed(f"Return qty for batch {batch.batch_no} must be between 0 and {batch.qty_on_hand:g}")
        ret.lines.append(SupplierReturnLine(product_id=batch.product_id, batch_id=batch.id, qty=qty,
                                            unit_price=batch.cost_price, gst_rate=batch.product.gst_rate,
                                            reason=e.get("reason") or reason))
        calc.append((qty, batch.cost_price, batch.product.gst_rate))
    business = settings_svc.get(db, "business")
    t = gst.totals(calc, gst.is_interstate(business.get("state"), supplier.state))
    ret.subtotal, ret.tax, ret.total = t.subtotal, t.tax, t.total
    db.add(ret)
    db.flush()
    record_initial(db, supplier_return, ret, actor=user, note=reason)
    audit.created(db, user, ret, "supplier_return")
    return ret


def get(db: Session, return_id: int) -> SupplierReturn:
    r = db.get(SupplierReturn, return_id)
    if not r:
        raise NotFound("Return not found")
    return r


def submit(db: Session, ret: SupplierReturn, user: User) -> SupplierReturn:
    transition(db, supplier_return, ret, RET.PENDING, actor=user)
    notify.notify_roles(db, [Role.MANAGER], f"Return {ret.return_no} needs approval",
                        f"{ret.supplier.name} · ₹{ret.total:,.2f}", link="/returns", channels={"in_app"})
    db.commit()
    return ret


def pdf(db: Session, ret: SupplierReturn) -> bytes:
    business = settings_svc.get(db, "business")
    data = documents.debit_note_pdf(ret, business, gst.is_interstate(business.get("state"), ret.supplier.state))
    ret.pdf_path = documents.save("debit_notes", ret.debit_note_no or ret.return_no, data)
    return data


def approve(db: Session, ret: SupplierReturn, user: User) -> SupplierReturn:
    transition(db, supplier_return, ret, RET.APPROVED, actor=user)
    ret.debit_note_no = numbering.next_number(db, SupplierReturn.debit_note_no, "DN")
    data = pdf(db, ret)
    business = settings_svc.get(db, "business")
    if ret.supplier.email:
        mailer.send_email(
            ret.supplier.email, f"Debit note {ret.debit_note_no} from {business['name']}",
            mailer.layout(f"Debit note {ret.debit_note_no}",
                          f"<p>We are returning goods against return {ret.return_no} ({ret.reason or 'see attached'}). "
                          f"Please issue a credit note for ₹{ret.total:,.2f}.</p>", business["name"]),
            attachments=[(f"{ret.debit_note_no}.pdf", data, "application/pdf")])
    db.commit()
    return ret


def reject(db: Session, ret: SupplierReturn, user: User, reason: str | None) -> SupplierReturn:
    transition(db, supplier_return, ret, RET.REJECTED, actor=user, note=reason)
    db.commit()
    return ret


def cancel(db: Session, ret: SupplierReturn, user: User, reason: str | None) -> SupplierReturn:
    transition(db, supplier_return, ret, RET.CANCELLED, actor=user, note=reason)
    db.commit()
    return ret


def dispatch(db: Session, ret: SupplierReturn, user: User) -> SupplierReturn:
    transition(db, supplier_return, ret, RET.DISPATCHED, actor=user)
    for ln in ret.lines:
        batch = stock.lock_batch(db, ln.batch_id) if ln.batch_id else None
        if not batch:
            raise ValidationFailed("Returned batch no longer exists")
        take = min(ln.qty, batch.qty_on_hand)
        batch.qty_on_hand = round(batch.qty_on_hand - take, 3)
        stock.record_movement(db, product_id=ln.product_id, location_id=batch.location_id, batch=batch,
                        mtype=MovementType.RETURN_OUT, qty=-take, unit_cost=ln.unit_price, user=user,
                        ref_type="supplier_return", ref_id=ret.id, note=f"Return {ret.return_no}")
    db.commit()
    return ret


def credit(db: Session, ret: SupplierReturn, user: User, credit_note_ref: str) -> SupplierReturn:
    if not credit_note_ref or not credit_note_ref.strip():
        raise ValidationFailed("Enter the supplier's credit note number")
    transition(db, supplier_return, ret, RET.CREDIT, actor=user, note=f"Credit note {credit_note_ref}")
    ret.credit_note_ref = credit_note_ref.strip()
    db.commit()
    return ret
