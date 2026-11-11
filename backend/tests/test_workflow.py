import itertools
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.errors import Conflict, Forbidden, InvalidTransition, ValidationFailed
from app.core.timeutil import now
from app.models import (
    Alert,
    ApprovalRule,
    ApprovalToken,
    Batch,
    Feedback,
    OrderStatusHistory,
    PurchaseOrder,
    StockMovement,
    SupplierReturn,
)
from app.services import gst, mailer, stock
from app.workflow import approvals, purchasing, receiving, returns
from app.workflow.engine import transition
from app.workflow.machines import ALL_MACHINES
from tests.factories import in_days


@pytest.fixture()
def rules(db):
    for a, b, role, auto in [(0, 5000, None, True), (5000, 50000, "manager", False), (50000, None, "admin", False)]:
        db.add(ApprovalRule(min_amount=a, max_amount=b, approver_role=role, auto_approve=auto))
    db.flush()


def make_pr(db, world, qty, supplier=None, submit=True):
    rice = world.products[0]  # supplier price 88 from Acme (Maharashtra), 85 from Delhi
    return purchasing.create_request(db, product_id=rice.id, location_id=world.store.id, qty=qty,
                                     supplier_id=(supplier or world.supplier).id, user=world.users["manager"],
                                     reason_text="test", submit=submit)


# ------------------------------------------------------------------ GST

def test_gst_split_intra_vs_inter_state():
    intra = gst.line_tax(10, 100, 18, interstate=False)
    assert (intra.taxable, intra.cgst, intra.sgst, intra.igst, intra.total) == (1000, 90, 90, 0, 1180)
    inter = gst.line_tax(10, 100, 18, interstate=True)
    assert (inter.cgst, inter.sgst, inter.igst) == (0, 0, 180)
    odd = gst.line_tax(1, 33.33, 5, interstate=False)
    assert round(odd.cgst + odd.sgst, 2) == round(33.33 * 0.05, 2)
    t = gst.totals([(2, 50, 5), (1, 100, 12)], interstate=False)
    assert (t.subtotal, t.tax, t.total) == (200, 17, 217)
    assert gst.is_interstate("Maharashtra", "Delhi") and not gst.is_interstate("Maharashtra", " maharashtra ")
    summary = gst.rate_summary([(2, 50, 5), (1, 100, 12)], interstate=True)
    assert [s["igst"] for s in summary] == [5, 12]


# ------------------------------------------------------------------ routing & approvals

def test_route_boundaries(db, rules):
    assert approvals.route(db, 0) == []
    assert approvals.route(db, 5000) == []
    assert approvals.route(db, 5000.01) == ["manager"]
    assert approvals.route(db, 50000) == ["manager"]
    assert approvals.route(db, 50001) == ["manager", "admin"]


def test_auto_approve_and_po_created(db, world, rules):
    pr = make_pr(db, world, 10)  # 10 × 88 = 880 → auto
    assert pr.status == "APPROVED" and pr.approvals[0].via == "auto"
    pos = purchasing.create_purchase_orders(db, actor=None, pr_ids=[pr.id])
    assert len(pos) == 1 and pos[0].status == "SENT" and pr.status == "ORDERED"
    po = pos[0]
    assert po.po_no.startswith("PO-") and len(po.po_no) == len("PO-202611-0001")
    assert po.cgst == po.sgst == round(880 * 0.05 / 2, 2) and po.igst == 0  # same state
    sent = [m for m in mailer.OUTBOX if m.subject.startswith("Purchase order")]
    assert sent and sent[0].attachments[0][0] == f"{po.po_no}.pdf" and sent[0].attachments[0][1][:4] == b"%PDF"
    assert "portal/orders" in sent[0].html


def test_interstate_po_uses_igst(db, world, rules):
    pr = make_pr(db, world, 20, supplier=world.other_supplier)  # Delhi supplier
    po = purchasing.create_purchase_orders(db, actor=None, pr_ids=[pr.id])[0]
    assert po.is_interstate and po.cgst == 0 and po.igst == round(20 * 85 * 0.05, 2)


def test_manager_level_approval_with_edit_writes_feedback(db, world, rules):
    pr = make_pr(db, world, 100)  # 8,800 → manager
    assert pr.status == "PENDING_APPROVAL" and [a.approver_role for a in pr.approvals] == ["manager"]
    assert any("Approval needed" in m.subject for m in mailer.OUTBOX)
    with pytest.raises(Forbidden):
        approvals.decide(db, pr, world.users["staff"], "approve")
    approvals.decide(db, pr, world.users["manager"], "approve", final_qty=120, create_po=False)
    assert pr.status == "APPROVED" and pr.final_qty == 120 and pr.est_total == 120 * 88
    fb = db.scalar(select(Feedback).where(Feedback.purchase_request_id == pr.id))
    assert fb.decision == "edited" and fb.suggested_qty == 100 and fb.final_qty == 120


def test_two_level_approval_manager_then_admin(db, world, rules):
    pr = make_pr(db, world, 600)  # 52,800 → manager then admin
    assert [a.approver_role for a in pr.approvals] == ["manager", "admin"]
    approvals.decide(db, pr, world.users["manager"], "approve")
    assert pr.status == "PENDING_APPROVAL" and approvals.current_approval(pr).approver_role == "admin"
    with pytest.raises(Forbidden):
        approvals.decide(db, pr, world.users["manager"], "approve")
    approvals.decide(db, pr, world.users["admin"], "approve")
    assert pr.status == "ORDERED" and pr.po_id  # PO auto-created and sent on final approval


def test_reject_requires_reason(db, world, rules):
    pr = make_pr(db, world, 100)
    with pytest.raises(ValidationFailed):
        approvals.decide(db, pr, world.users["manager"], "reject", comment=" ")
    approvals.decide(db, pr, world.users["manager"], "reject", comment="Enough stock")
    assert pr.status == "REJECTED" and pr.rejection_reason == "Enough stock"
    with pytest.raises(InvalidTransition):
        approvals.decide(db, pr, world.users["manager"], "approve")


def test_supplier_change_on_approval_reprices(db, world, rules):
    pr = make_pr(db, world, 100)
    approvals.decide(db, pr, world.users["manager"], "approve", final_supplier_id=world.other_supplier.id, create_po=False)
    assert pr.final_supplier_id == world.other_supplier.id and pr.est_unit_price == 85


def test_bulk_approve_groups_into_one_po(db, world, rules):
    rice, milk = world.products
    a = make_pr(db, world, 100)
    b = purchasing.create_request(db, product_id=milk.id, location_id=world.store.id, qty=300, supplier_id=world.supplier.id,
                                  user=world.users["manager"])
    res = approvals.bulk_approve(db, [a.id, b.id, 999999], world.users["manager"])
    assert sorted(res["approved"]) == sorted([a.id, b.id]) and res["failed"][0]["id"] == 999999
    assert len(res["purchase_orders"]) == 1 and a.po_id == b.po_id


# ------------------------------------------------------------------ one-click tokens

def tokens_for(db, pr, user, action, channel="em"):
    # raw tokens are only in emails; fetch them from the outbox for this user
    for m in reversed(mailer.OUTBOX):
        if user.email in m.to and f"#{pr.id}" in m.subject:
            marker = "approval?token="
            links = [part.split('"')[0] for part in m.html.split(marker)[1:]]
            return links[0] if action == "approve" else links[1]
    raise AssertionError("no approval email")


def test_one_click_token_single_use_and_expiry(client, db, world, rules):
    pr = make_pr(db, world, 100)
    db.commit()
    mgr = world.users["manager"]
    approve = tokens_for(db, pr, mgr, "approve")
    reject = tokens_for(db, pr, mgr, "reject")
    info = client.get(f"/api/v1/approvals/token/{approve}").json()
    assert info["action"] == "approve" and info["request"]["id"] == pr.id
    assert client.post(f"/api/v1/approvals/token/{reject}", json={}).status_code == 422  # reason required
    r = client.post(f"/api/v1/approvals/token/{approve}", json={})
    assert r.status_code == 200 and r.json()["status"] in ("APPROVED", "ORDERED")
    again = client.post(f"/api/v1/approvals/token/{approve}", json={})
    assert again.status_code == 422 and again.json()["code"] == "token_used"
    assert client.get("/api/v1/approvals/token/nope").status_code == 404

    pr2 = make_pr(db, world, 200)
    db.commit()
    tok = tokens_for(db, pr2, mgr, "approve")
    for t in db.scalars(select(ApprovalToken)):
        t.expires_at = now() - timedelta(minutes=1)
    db.commit()
    r = client.post(f"/api/v1/approvals/token/{tok}", json={})
    assert r.status_code == 422 and r.json()["code"] == "token_expired"


def test_telegram_token_records_via(db, world, rules):
    pr = make_pr(db, world, 100)
    raw_tg = approvals._issue_tokens(db, pr.approvals[0], world.users["manager"])["tg_approve"]
    db.flush()
    approvals.use_token(db, raw_tg, None)
    assert pr.approvals[0].via == "telegram"


# ------------------------------------------------------------------ state machines

@pytest.mark.parametrize("machine", ALL_MACHINES, ids=lambda m: m.name)
def test_every_invalid_transition_raises(db, machine):
    states = sorted(machine.states)
    invalid = [(a, b) for a, b in itertools.product(states, states) if not machine.can(a, b)]
    assert invalid
    for a, b in invalid:
        with pytest.raises(InvalidTransition):
            transition(db, machine, SimpleNamespace(status=a, id=1), b)
    for terminal in machine.terminal:
        assert not machine.transitions.get(terminal)


def test_api_invalid_transition_is_409(client, auth, db, world, rules):
    pr = make_pr(db, world, 10)  # auto-approved
    db.commit()
    r = client.post(f"/api/v1/purchase-requests/{pr.id}/decide", headers=auth("manager"), json={"action": "approve"})
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"


# ------------------------------------------------------------------ full cycle, portal, GRN, match

def _po(db, world, qty=100, supplier=None):
    pr = make_pr(db, world, qty, supplier=supplier, submit=True)
    if pr.status == "PENDING_APPROVAL":
        approvals.decide(db, pr, world.users["manager"], "approve")
    else:
        purchasing.create_purchase_orders(db, actor=None, pr_ids=[pr.id])
    db.commit()
    return db.get(PurchaseOrder, pr.po_id)


def test_full_purchase_cycle_via_api(client, auth, db, world, rules):
    po = _po(db, world, 100)
    sup_h, other_h, staff_h, mgr_h = auth("supplier"), auth("supplier2"), auth("staff"), auth("manager")
    assert client.get(f"/api/v1/portal/orders/{po.id}", headers=other_h).status_code == 403  # isolation
    assert client.get(f"/api/v1/portal/orders/{po.id}/pdf", headers=other_h).status_code == 403
    assert po.id not in [o["id"] for o in client.get("/api/v1/portal/orders", headers=other_h).json()["items"]]
    assert client.get("/api/v1/purchase-orders", headers=sup_h).status_code == 403
    r = client.post(f"/api/v1/portal/orders/{po.id}/confirm", headers=sup_h, json={"eta": str(in_days(3))})
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    r = client.post(f"/api/v1/portal/orders/{po.id}/dispatch", headers=sup_h,
                    json={"eta": str(in_days(2)), "tracking_ref": "LR123", "courier_name": "VRL"})
    assert r.json()["status"] == "DISPATCHED"
    line = po.lines[0]
    before = stock.position(db, line.product_id, world.store.id)["on_hand"]
    r = client.post(f"/api/v1/purchase-orders/{po.id}/grn", headers=staff_h, json={"lines": [
        {"po_line_id": line.id, "received_qty": 60, "batch_no": "G1", "expiry_date": str(in_days(300))}]})
    assert r.status_code == 201 and r.json()["po"]["status"] == "PARTIALLY_RECEIVED"
    too_many = client.post(f"/api/v1/purchase-orders/{po.id}/grn", headers=staff_h,
                           json={"lines": [{"po_line_id": line.id, "received_qty": 41}]})
    assert too_many.status_code == 422
    r = client.post(f"/api/v1/purchase-orders/{po.id}/grn", headers=staff_h, json={"lines": [
        {"po_line_id": line.id, "received_qty": 40, "batch_no": "G2"}]})
    assert r.json()["po"]["status"] == "RECEIVED"
    assert stock.position(db, line.product_id, world.store.id)["on_hand"] == before + 100
    r = client.post(f"/api/v1/portal/orders/{po.id}/invoice", headers=sup_h,
                    data={"invoice_no": "ACME/101", "invoice_date": str(in_days(0))})
    assert r.status_code == 201 and r.json()["status"] == "matched"
    detail = client.get(f"/api/v1/purchase-orders/{po.id}", headers=mgr_h).json()
    assert detail["status"] == "CLOSED"
    assert [t["to"] for t in detail["timeline"]] == ["CREATED", "SENT", "CONFIRMED", "DISPATCHED", "PARTIALLY_RECEIVED",
                                                     "RECEIVED", "INVOICED", "CLOSED"]
    assert detail["matches"][0]["status"] == "matched"
    pdf = client.get(f"/api/v1/purchase-orders/{po.id}/pdf", headers=staff_h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


@pytest.mark.parametrize(("price_factor", "qty_delta", "expected"), [(1.019, 0, "matched"), (1.021, 0, "mismatch"),
                                                                      (1.0, 1, "mismatch"), (0.98, 0, "matched")])
def test_three_way_tolerance(db, world, rules, price_factor, qty_delta, expected):
    po = _po(db, world, 50)
    ln = po.lines[0]
    receiving.receive(db, po, [{"po_line_id": ln.id, "received_qty": 50}], world.users["staff"])
    inv = receiving.record_invoice(db, po, invoice_no=f"INV-{price_factor}-{qty_delta}", invoice_date=in_days(0),
                                   lines=[{"po_line_id": ln.id, "qty": 50 + qty_delta,
                                           "unit_price": round(ln.unit_price * price_factor, 2)}], user=world.users["manager"])
    assert inv.status == expected
    assert po.status == ("CLOSED" if expected == "matched" else "INVOICED")


def test_mismatch_blocks_close_until_resolved(client, auth, db, world, rules):
    po = _po(db, world, 50)
    ln = po.lines[0]
    receiving.receive(db, po, [{"po_line_id": ln.id, "received_qty": 50}], world.users["staff"])
    receiving.record_invoice(db, po, invoice_no="BAD-1", invoice_date=in_days(0),
                             lines=[{"po_line_id": ln.id, "qty": 50, "unit_price": ln.unit_price * 1.1}],
                             user=world.users["manager"])
    alert = db.scalar(select(Alert).where(Alert.type == "three_way_mismatch", Alert.ref_id == po.id))
    assert alert and alert.severity == "critical"
    h = auth("manager")
    assert client.post(f"/api/v1/purchase-orders/{po.id}/close", headers=h).status_code == 409
    match_id = client.get(f"/api/v1/purchase-orders/{po.id}", headers=h).json()["matches"][0]["id"]
    assert client.post(f"/api/v1/matches/{match_id}/resolve", headers=auth("staff"), json={"note": "ok"}).status_code == 403
    r = client.post(f"/api/v1/matches/{match_id}/resolve", headers=h, json={"note": "Supplier agreed credit note"})
    assert r.status_code == 200 and r.json()["status"] == "CLOSED"
    db.refresh(alert)
    assert alert.status == "resolved"


def test_supplier_reject_and_invalid_supplier_action(client, auth, db, world, rules):
    po = _po(db, world, 100)
    h = auth("supplier")
    assert client.post(f"/api/v1/portal/orders/{po.id}/reject", headers=h, json={"reason": "Out of stock"}).json()["status"] \
        == "REJECTED_BY_SUPPLIER"
    r = client.post(f"/api/v1/portal/orders/{po.id}/confirm", headers=h, json={})
    assert r.status_code == 409


def test_damaged_goods_quarantine_and_return_flow(db, world, rules):
    po = _po(db, world, 100)
    ln = po.lines[0]
    receiving.receive(db, po, [{"po_line_id": ln.id, "received_qty": 95, "damaged_qty": 5, "batch_no": "D1"}],
                      world.users["staff"])
    assert po.status == "RECEIVED"
    q = db.scalar(select(Batch).where(Batch.batch_no == "DMG-D1"))
    assert q.is_blocked and q.qty_on_hand == 5
    assert stock.position(db, ln.product_id, world.store.id)["on_hand"] == 95  # quarantine not sellable
    ret = db.scalar(select(SupplierReturn).where(SupplierReturn.po_id == po.id))
    assert ret.status == "DRAFT" and ret.lines[0].qty == 5
    mgr = world.users["manager"]
    with pytest.raises(InvalidTransition):
        returns.dispatch(db, ret, mgr)
    returns.submit(db, ret, mgr)
    mailer.OUTBOX.clear()
    returns.approve(db, ret, mgr)
    assert ret.debit_note_no.startswith("DN-") and mailer.OUTBOX[0].attachments[0][1][:4] == b"%PDF"
    returns.dispatch(db, ret, mgr)
    assert q.qty_on_hand == 0
    out = db.scalar(select(StockMovement).where(StockMovement.type == "return_out", StockMovement.reference_id == ret.id))
    assert out.qty == -5
    with pytest.raises(ValidationFailed):
        returns.credit(db, ret, mgr, "")
    returns.credit(db, ret, mgr, "CN-778")
    assert ret.status == "CREDIT_RECEIVED"


def test_grn_rejected_on_closed_or_unsent_po(db, world, rules):
    po = _po(db, world, 10)
    po.status = "CLOSED"
    with pytest.raises(Conflict):
        receiving.receive(db, po, [{"po_line_id": po.lines[0].id, "received_qty": 1}], world.users["staff"])


def test_cancel_po_requires_reason_and_writes_history(db, world, rules):
    po = _po(db, world, 10)
    with pytest.raises(ValidationFailed):
        purchasing.cancel_po(db, po, world.users["manager"], None)
    purchasing.cancel_po(db, po, world.users["manager"], "Duplicate order")
    hist = db.scalars(select(OrderStatusHistory).where(OrderStatusHistory.po_id == po.id)).all()
    assert hist[-1].to_status == "CANCELLED" and hist[-1].note == "Duplicate order"


# ------------------------------------------------------------------ SLA, notifications

def test_sla_reminder_then_escalation(db, world, rules):
    pr = make_pr(db, world, 100)
    pr.submitted_at = now() - timedelta(hours=25)
    mailer.OUTBOX.clear()
    assert approvals.check_sla(db) == {"reminded": 1, "escalated": 0}
    assert any(m.subject.startswith("Reminder") for m in mailer.OUTBOX)
    assert approvals.check_sla(db) == {"reminded": 0, "escalated": 0}  # only once
    pr.submitted_at = now() - timedelta(hours=49)
    assert approvals.check_sla(db) == {"reminded": 0, "escalated": 1}
    assert any("admin@test.in" in m.to and m.subject.startswith("Escalated") for m in mailer.OUTBOX)
    alert = db.scalar(select(Alert).where(Alert.type == "approval_pending"))
    assert alert.severity == "critical"
    approvals.decide(db, pr, world.users["admin"], "approve", create_po=False)  # admin can act on escalated item
    assert pr.status == "APPROVED"


def test_notifications_bell(client, auth, db, world, rules):
    make_pr(db, world, 100)
    db.commit()
    h = auth("manager")
    n = client.get("/api/v1/notifications/unread-count", headers=h).json()["unread"]
    assert n >= 1
    items = client.get("/api/v1/notifications", headers=h).json()["items"]
    assert client.post(f"/api/v1/notifications/{items[0]['id']}/read", headers=h).status_code == 200
    assert client.post(f"/api/v1/notifications/{items[0]['id']}/read", headers=auth("staff")).status_code == 404
    client.post("/api/v1/notifications/read-all", headers=h)
    assert client.get("/api/v1/notifications/unread-count", headers=h).json()["unread"] == 0


def test_rejection_streak_lowers_priority(db, world, rules):
    rice = world.products[0]
    for _ in range(3):
        pr = purchasing.create_request(db, product_id=rice.id, location_id=world.store.id, qty=100,
                                       supplier_id=world.supplier.id, user=None, created_by="agent")
        approvals.decide(db, pr, world.users["manager"], "reject", comment="not needed")
    assert rice.priority == -1
    assert db.scalar(select(Alert).where(Alert.type == "suggestion_rejected", Alert.product_id == rice.id))


def test_approval_rules_api_validation(client, auth, world, rules):
    h = auth("admin")
    bad = client.put("/api/v1/approval-rules", headers=h, json=[{"min_amount": 0, "max_amount": 1000, "auto_approve": True},
                                                               {"min_amount": 2000, "approver_role": "manager"}])
    assert bad.status_code == 422
    ok = client.put("/api/v1/approval-rules", headers=h, json=[
        {"min_amount": 0, "max_amount": 2000, "auto_approve": True},
        {"min_amount": 2000, "max_amount": 20000, "approver_role": "manager"},
        {"min_amount": 20000, "approver_role": "admin"}])
    assert ok.status_code == 200 and len(ok.json()) == 3
    assert client.get("/api/v1/approval-rules/route", headers=auth("manager"), params={"amount": 30000}).json()["levels"] \
        == ["manager", "admin"]
    assert client.put("/api/v1/approval-rules", headers=auth("manager"), json=[]).status_code == 403
