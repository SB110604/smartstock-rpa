"""Goods receipt, supplier invoice and 3-way match (spec 8.3, 8.4)."""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.timeutil import now
from app.models.core import Role, User
from app.models.purchasing import (
    GoodsReceipt,
    GrnLine,
    PurchaseOrder,
    SupplierInvoice,
    SupplierInvoiceLine,
    ThreeWayMatch,
)
from app.services import alerts, audit, gst, notify, numbering, stock
from app.services import settings as settings_svc
from app.workflow.engine import transition
from app.workflow.machines import PO, purchase_order

EPS = 1e-6


def receive(db: Session, po: PurchaseOrder, lines: list[dict[str, Any]], user: User, note: str | None = None) -> GoodsReceipt:
    """Record a (possibly partial) delivery. received_qty = good units into stock; damaged_qty = units that arrived
    damaged — they go to a blocked quarantine batch and onto a supplier-return draft."""
    if po.status not in PO.RECEIVABLE:
        raise Conflict(f"Goods cannot be received on a PO in status {po.status}", code="invalid_transition")
    by_id = {ln.id: ln for ln in po.lines}
    entries = [e for e in lines if float(e.get("received_qty") or 0) + float(e.get("damaged_qty") or 0) > 0]
    if not entries:
        raise ValidationFailed("Enter a received or damaged quantity for at least one line")
    grn = GoodsReceipt(grn_no=numbering.next_number(db, GoodsReceipt.grn_no, "GRN"), po_id=po.id, location_id=po.location_id,
                       received_by=user.id, received_at=now(), note=note)
    db.add(grn)
    db.flush()
    damaged_lines: list[dict[str, Any]] = []
    for e in entries:
        pl = by_id.get(int(e["po_line_id"]))
        if not pl:
            raise NotFound(f"PO line {e['po_line_id']} not found")
        rec, dmg = float(e.get("received_qty") or 0), float(e.get("damaged_qty") or 0)
        if rec < 0 or dmg < 0:
            raise ValidationFailed("Quantities cannot be negative")
        remaining = pl.qty - pl.received_qty - pl.damaged_qty
        if rec + dmg > remaining + EPS:
            raise ValidationFailed(f"{pl.product.name}: only {remaining:g} remaining on this PO")
        expiry: date | None = e.get("expiry_date")
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry) if expiry else None
        batch_no = (e.get("batch_no") or "").strip() or f"{po.po_no[-4:]}-{pl.id}"
        gl = GrnLine(grn_id=grn.id, po_line_id=pl.id, product_id=pl.product_id, received_qty=rec, damaged_qty=dmg,
                     batch_no=batch_no, expiry_date=expiry)
        db.add(gl)
        db.flush()
        if rec > 0:
            b = stock.receive(db, product=pl.product, location_id=po.location_id, qty=rec, batch_no=batch_no,
                              expiry_date=expiry, unit_cost=pl.unit_price, user=user, ref_type="grn", ref_id=grn.id,
                              supplier_id=po.supplier_id, grn_line_id=gl.id, note=f"GRN {grn.grn_no} / {po.po_no}")
            gl.expiry_date = b.expiry_date
        if dmg > 0:
            q = stock.receive(db, product=pl.product, location_id=po.location_id, qty=dmg, batch_no=f"DMG-{batch_no}",
                              expiry_date=expiry or gl.expiry_date, unit_cost=pl.unit_price, user=user, ref_type="grn",
                              ref_id=grn.id, supplier_id=po.supplier_id, grn_line_id=gl.id,
                              note=f"Damaged on delivery — quarantined ({grn.grn_no})")
            q.is_blocked = True
            damaged_lines.append({"batch_id": q.id, "qty": dmg, "reason": "Damaged on delivery"})
        pl.received_qty = round(pl.received_qty + rec, 3)
        pl.damaged_qty = round(pl.damaged_qty + dmg, 3)
    complete = all(ln.received_qty + ln.damaged_qty >= ln.qty - EPS for ln in po.lines)
    target = PO.RECEIVED if complete else PO.PARTIAL
    if po.status != target:
        transition(db, purchase_order, po, target, actor=user, note=f"{grn.grn_no}")
    po.delivered_at = now()
    po.courier_status = "Delivered" if complete else "Partially delivered"
    audit.created(db, user, grn, "goods_receipt")
    if damaged_lines:
        from app.workflow import returns

        returns.create(db, supplier_id=po.supplier_id, location_id=po.location_id, lines=damaged_lines, po_id=po.id,
                       reason=f"Damaged goods received on {grn.grn_no}", user=user)
    if complete:
        inv = latest_invoice(db, po)
        if inv:
            match(db, po, inv, user)
    notify.notify_roles(db, [Role.MANAGER], f"Goods received on {po.po_no}",
                        f"{grn.grn_no}: {len(entries)} line(s)" + (" — damaged items quarantined" if damaged_lines else ""),
                        link=f"/orders/{po.id}", channels={"in_app"})
    db.commit()
    return grn


def latest_invoice(db: Session, po: PurchaseOrder) -> SupplierInvoice | None:
    return db.scalar(select(SupplierInvoice).where(SupplierInvoice.po_id == po.id).order_by(SupplierInvoice.id.desc()))


def record_invoice(db: Session, po: PurchaseOrder, *, invoice_no: str, invoice_date: date, lines: list[dict[str, Any]],
                   user: User | None, source: str = "manual", file_path: str | None = None,
                   ocr_text: str | None = None) -> SupplierInvoice:
    if po.status in (PO.CANCELLED, PO.REJECTED, PO.CLOSED, PO.CREATED):
        raise Conflict(f"Cannot record an invoice on a PO in status {po.status}", code="invalid_transition")
    if not invoice_no.strip():
        raise ValidationFailed("Invoice number is required")
    dup = db.scalar(select(SupplierInvoice).where(SupplierInvoice.supplier_id == po.supplier_id,
                                                  SupplierInvoice.invoice_no == invoice_no.strip()))
    if dup:
        raise Conflict(f"Invoice {invoice_no} from this supplier is already recorded", code="duplicate_invoice")
    by_id = {ln.id: ln for ln in po.lines}
    inv = SupplierInvoice(invoice_no=invoice_no.strip(), supplier_id=po.supplier_id, po_id=po.id, invoice_date=invoice_date,
                          source=source, file_path=file_path, ocr_text=ocr_text, created_by=user.id if user else None)
    calc = []
    for e in lines:
        pl = by_id.get(int(e["po_line_id"])) if e.get("po_line_id") else None
        product_id = e.get("product_id") or (pl.product_id if pl else None)
        if pl is None and product_id:
            pl = next((ln for ln in po.lines if ln.product_id == int(product_id)), None)
        rate = float(e.get("gst_rate") if e.get("gst_rate") is not None else (pl.gst_rate if pl else 0))
        qty, price = float(e["qty"]), float(e["unit_price"])
        if qty < 0 or price < 0:
            raise ValidationFailed("Invoice quantities and prices cannot be negative")
        inv.lines.append(SupplierInvoiceLine(product_id=product_id, po_line_id=pl.id if pl else None,
                                             description=e.get("description") or (pl.product.name if pl else None),
                                             qty=qty, unit_price=price, gst_rate=rate))
        calc.append((qty, price, rate))
    if not inv.lines:
        raise ValidationFailed("An invoice needs at least one line")
    t = gst.totals(calc, po.is_interstate)
    inv.subtotal, inv.tax, inv.total = t.subtotal, t.tax, t.total
    db.add(inv)
    db.flush()
    audit.created(db, user, inv, "supplier_invoice")
    if po.status == PO.RECEIVED:
        match(db, po, inv, user)
    db.commit()
    return inv


def match(db: Session, po: PurchaseOrder, inv: SupplierInvoice, user: User | None) -> ThreeWayMatch:
    """Compare PO vs GRN vs invoice per line using the configured tolerances; mismatch blocks closing."""
    tol = settings_svc.get(db, "match_tolerance")
    qty_tol, price_tol = float(tol["qty_pct"]), float(tol["price_pct"])
    inv_by_line: dict[int, list[SupplierInvoiceLine]] = {}
    unmatched_invoice = []
    for il in inv.lines:
        if il.po_line_id:
            inv_by_line.setdefault(il.po_line_id, []).append(il)
        else:
            unmatched_invoice.append(il)
    details = []
    ok_all = not unmatched_invoice
    for pl in po.lines:
        ils = inv_by_line.get(pl.id, [])
        inv_qty = sum(il.qty for il in ils)
        inv_price = (sum(il.qty * il.unit_price for il in ils) / inv_qty) if inv_qty else 0.0
        grn_qty = pl.received_qty
        qty_ok = abs(inv_qty - grn_qty) <= grn_qty * qty_tol / 100 + EPS
        diff = (inv_price - pl.unit_price) / pl.unit_price * 100 if pl.unit_price else 0.0
        price_ok = (inv_qty == 0 and grn_qty == 0) or abs(diff) <= price_tol + EPS
        status = "matched" if qty_ok and price_ok else "mismatch"
        ok_all = ok_all and status == "matched"
        details.append({"po_line_id": pl.id, "product_id": pl.product_id, "product": pl.product.name, "po_qty": pl.qty,
                        "grn_qty": grn_qty, "invoice_qty": inv_qty, "po_price": pl.unit_price,
                        "invoice_price": round(inv_price, 2), "price_diff_pct": round(diff, 2), "qty_ok": qty_ok,
                        "price_ok": price_ok, "status": status})
    for il in unmatched_invoice:
        details.append({"po_line_id": None, "product_id": il.product_id, "product": il.description, "po_qty": 0,
                        "grn_qty": 0, "invoice_qty": il.qty, "po_price": 0, "invoice_price": il.unit_price,
                        "price_diff_pct": None, "qty_ok": False, "price_ok": False, "status": "mismatch",
                        "note": "Billed item not on the PO"})
    grn = db.scalar(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id).order_by(GoodsReceipt.id.desc()))
    m = db.scalar(select(ThreeWayMatch).where(ThreeWayMatch.invoice_id == inv.id))
    status = "matched" if ok_all else "mismatch"
    payload = {"lines": details, "tolerance": {"qty_pct": qty_tol, "price_pct": price_tol},
               "invoice_total": inv.total, "po_total": po.total}
    if m:
        m.status, m.details_json, m.grn_id = status, payload, grn.id if grn else None
    else:
        m = ThreeWayMatch(po_id=po.id, grn_id=grn.id if grn else None, invoice_id=inv.id, status=status, details_json=payload)
        db.add(m)
    inv.status = status
    if po.status == PO.RECEIVED:
        transition(db, purchase_order, po, PO.INVOICED, actor=user, note=f"Invoice {inv.invoice_no} — 3-way {status}")
    db.flush()
    audit.record(db, user, "three_way_match", "purchase_order", po.id, None, {"status": status, "invoice": inv.invoice_no})
    if ok_all:
        alerts.resolve_by_key(db, f"three_way_mismatch:{po.id}", "matched")
        close(db, po, user, note="Auto-closed after successful 3-way match")
    else:
        bad = [d for d in details if d["status"] == "mismatch"]
        msg = "; ".join(
            f"{d['product']}: GRN {d['grn_qty']:g} vs invoice {d['invoice_qty']:g} @ ₹{d['invoice_price']:g}"
            + (f" ({d['price_diff_pct']:+.1f}%)" if d.get("price_diff_pct") is not None else "") for d in bad[:3])
        alerts.raise_alert(db, "three_way_mismatch", f"3-way mismatch on {po.po_no} ({po.supplier.name}): {msg}",
                           severity="critical", ref_type="purchase_order", ref_id=po.id, key=f"three_way_mismatch:{po.id}",
                           data={"match_id": m.id, "lines": bad})
    return m


def resolve_mismatch(db: Session, m: ThreeWayMatch, user: User, note: str) -> ThreeWayMatch:
    if m.status != "mismatch":
        raise Conflict("Only mismatched results can be resolved")
    if not note or not note.strip():
        raise ValidationFailed("Explain how the mismatch was resolved (e.g. credit note agreed)")
    m.status, m.resolved_by, m.resolved_at, m.resolution_note = "resolved", user.id, now(), note.strip()
    inv = db.get(SupplierInvoice, m.invoice_id)
    if inv:
        inv.status = "resolved"
    po = db.get(PurchaseOrder, m.po_id)
    assert po is not None
    audit.record(db, user, "resolve_mismatch", "purchase_order", po.id, {"status": "mismatch"},
                 {"status": "resolved", "note": note})
    alerts.resolve_by_key(db, f"three_way_mismatch:{po.id}", "resolved by manager")
    if po.status == PO.INVOICED:
        close(db, po, user, note=f"Closed after mismatch resolution: {note}")
    db.commit()
    return m


def close(db: Session, po: PurchaseOrder, user: User | None, note: str | None = None) -> PurchaseOrder:
    latest = db.scalar(select(ThreeWayMatch).where(ThreeWayMatch.po_id == po.id).order_by(ThreeWayMatch.id.desc()))
    if po.status == PO.INVOICED and (not latest or latest.status == "mismatch"):
        raise Conflict("PO cannot be closed until the 3-way mismatch is resolved by a manager", code="match_blocked")
    transition(db, purchase_order, po, PO.CLOSED, actor=user, actor_type=None if user else "system", note=note)
    po.closed_at = now()
    return po
