import pytest
from sqlalchemy import select

from app.core.errors import Conflict, InvalidTransition, ValidationFailed
from app.models import AuditLog, Batch, StatusHistory, StockMovement
from app.services import counts, sales, stock
from app.workflow import transfers
from tests.factories import in_days, make_batch


def test_plan_fefo_takes_earliest_expiry_first(world, db):
    rice = world.products[0]
    late = make_batch(db, rice, world.store, 5, in_days(60), "LATE")
    soon = make_batch(db, rice, world.store, 3, in_days(5), "SOON")
    never = make_batch(db, rice, world.store, 10, None, "NOEXP")
    ordered = stock.fefo_batches(db, rice.id, world.store.id)
    assert [b.batch_no for b in ordered] == ["SOON", "LATE", "NOEXP"]
    picks = stock.plan_fefo(ordered, 7)
    assert [(b.batch_no, q) for b, q in picks] == [("SOON", 3), ("LATE", 4)]
    assert never.qty_on_hand == 10 and soon.qty_on_hand == 3 and late.qty_on_hand == 5  # plan is pure


def test_fefo_skips_expired_and_blocked(world, db):
    rice = world.products[0]
    make_batch(db, rice, world.store, 50, in_days(-1), "EXPIRED")
    make_batch(db, rice, world.store, 50, in_days(3), "BLOCKED", is_blocked=True)
    ok = make_batch(db, rice, world.store, 4, in_days(10), "OK")
    assert [b.batch_no for b in stock.fefo_batches(db, rice.id, world.store.id)] == ["OK"]
    assert stock.position(db, rice.id, world.store.id)["on_hand"] == 4
    picks = stock.issue(db, product=rice, location_id=world.store.id, qty=4, movement_type="sale_out", user=None)
    assert picks[0][0].id == ok.id and ok.qty_on_hand == 0


def test_issue_insufficient_records_negative_attempt(world, db):
    rice = world.products[0]
    make_batch(db, rice, world.store, 2, in_days(30))
    with pytest.raises(Conflict) as exc:
        stock.issue(db, product=rice, location_id=world.store.id, qty=5, movement_type="sale_out",
                    user=world.users["staff"])
    assert exc.value.code == "insufficient_stock"
    attempts = db.scalars(select(AuditLog).where(AuditLog.action == "negative_stock_attempt")).all()
    assert len(attempts) == 1 and attempts[0].after_json["requested"] == 5


def test_sale_uses_fefo_markdown_and_backs_out_gst(world, db):
    rice = world.products[0]  # selling 120, gst 5%
    old = make_batch(db, rice, world.store, 2, in_days(4), "OLD", markdown_pct=25)
    make_batch(db, rice, world.store, 10, in_days(90), "NEW")
    sale = sales.create_sale(db, location_id=world.store.id, lines=[{"product_id": rice.id, "qty": 3}],
                             channel="manual", user=world.users["staff"])
    first = sale.lines[0]
    assert (first.batch_id, first.qty, first.unit_price) == (old.id, 2, 90.0)
    assert sale.lines[1].unit_price == 120.0
    assert sale.total == 300.0
    assert sale.tax == pytest.approx(round(180 * 5 / 105, 2) + round(120 * 5 / 105, 2))
    moves = db.scalars(select(StockMovement).where(StockMovement.reference_type == "sale",
                                                   StockMovement.reference_id == sale.id)).all()
    assert sorted(m.qty for m in moves) == [-2, -1]
    assert sale.invoice_no.startswith("INV-")


def test_receive_merges_same_batch_and_derives_perishable_expiry(world, db):
    rice, milk = world.products
    b1 = stock.receive(db, product=rice, location_id=world.store.id, qty=10, batch_no="R1", expiry_date=in_days(200),
                       unit_cost=80, user=None)
    b2 = stock.receive(db, product=rice, location_id=world.store.id, qty=10, batch_no="R1", expiry_date=in_days(200),
                       unit_cost=100, user=None)
    assert b1.id == b2.id and b2.qty_on_hand == 20 and b2.cost_price == 90
    m = stock.receive(db, product=milk, location_id=world.store.id, qty=5, batch_no=None, expiry_date=None,
                      unit_cost=None, user=None)
    assert m.expiry_date == in_days(4) and m.cost_price == milk.cost_price


def test_receive_rejects_bad_qty(world, db):
    with pytest.raises(ValidationFailed):
        stock.receive(db, product=world.products[0], location_id=world.store.id, qty=0, batch_no="X",
                      expiry_date=None, unit_cost=1, user=None)


def test_adjust_requires_reason_and_writes_movement(world, db):
    b = make_batch(db, world.products[0], world.store, 10, in_days(50))
    with pytest.raises(ValidationFailed):
        stock.adjust_batch(db, batch=b, new_qty=8, reason=" ", user=None)
    m = stock.adjust_batch(db, batch=b, new_qty=8, reason="Damaged in shelf", user=world.users["manager"])
    assert m.qty == -2 and m.type == "adjustment" and b.qty_on_hand == 8


def test_write_off_blocks_empty_batch(world, db):
    b = make_batch(db, world.products[1], world.store, 6, in_days(-2))
    stock.write_off(db, batch=b, qty=None, reason="Expired", user=world.users["manager"])
    assert b.qty_on_hand == 0 and b.is_blocked


def test_find_by_code_handles_barcode_sku_and_batch_qr(world, db):
    rice = world.products[0]
    b = make_batch(db, rice, world.store, 3, in_days(9), "QR1")
    assert stock.find_by_code(db, "8900000000011")[0].id == rice.id
    assert stock.find_by_code(db, "RICE-1")[0].id == rice.id
    p, batch = stock.find_by_code(db, "RICE-1|QR1")
    assert p.id == rice.id and batch.id == b.id
    assert stock.find_by_code(db, "nope") == (None, None)


def test_transfer_workflow_moves_batches(world, db):
    rice = world.products[0]
    make_batch(db, rice, world.warehouse, 5, in_days(20), "W1")
    make_batch(db, rice, world.warehouse, 5, in_days(40), "W2")
    mgr = world.users["manager"]
    tr = transfers.create(db, from_location_id=world.warehouse.id, to_location_id=world.store.id,
                          lines=[{"product_id": rice.id, "qty": 7}], note="refill", user=mgr)
    with pytest.raises(InvalidTransition):
        transfers.dispatch(db, tr, mgr)  # must be approved first
    transfers.approve(db, tr, mgr)
    transfers.dispatch(db, tr, mgr)
    assert sorted(ln.qty for ln in tr.lines) == [2, 5]
    assert stock.position(db, rice.id, world.warehouse.id)["on_hand"] == 3
    transfers.receive(db, tr, mgr)
    store_batches = db.scalars(select(Batch).where(Batch.location_id == world.store.id)).all()
    assert {b.batch_no: b.qty_on_hand for b in store_batches} == {"W1": 5, "W2": 2}
    hist = db.scalars(select(StatusHistory).where(StatusHistory.entity == "stock_transfer",
                                                  StatusHistory.entity_id == tr.id)).all()
    assert [h.to_status for h in hist] == ["REQUESTED", "APPROVED", "DISPATCHED", "RECEIVED"]
    with pytest.raises(InvalidTransition):
        transfers.cancel(db, tr, mgr, "late")


def test_transfer_same_location_rejected(world, db):
    with pytest.raises(ValidationFailed):
        transfers.create(db, from_location_id=world.store.id, to_location_id=world.store.id,
                         lines=[{"product_id": world.products[0].id, "qty": 1}], note=None, user=None)


def test_stock_count_variance_and_completion(world, db):
    rice, milk = world.products
    b = make_batch(db, rice, world.store, 10, in_days(100))
    staff, mgr = world.users["staff"], world.users["manager"]
    c = counts.start(db, location_id=world.store.id, category_id=None, product_ids=[rice.id, milk.id], note=None,
                     user=staff)
    lines = {(ln.product_id, ln.batch_id): ln for ln in c.lines}
    with pytest.raises(ValidationFailed):
        counts.complete(db, c, mgr)
    counts.record_counts(db, c, [{"line_id": lines[(rice.id, b.id)].id, "counted_qty": 8},
                                 {"line_id": lines[(milk.id, None)].id, "counted_qty": 3}], staff)
    report = counts.variance_report(c)
    assert report["summary"]["with_variance"] == 2
    result = counts.complete(db, c, mgr)
    assert result["adjustments"] == 2
    assert b.qty_on_hand == 8
    assert stock.position(db, milk.id, world.store.id)["on_hand"] == 3


def test_api_stock_in_out_and_lookup(client, auth, world):
    rice = world.products[0]
    h = auth("staff")
    r = client.post("/api/v1/stock/in", headers=h, json={"product_id": rice.id, "location_id": world.store.id,
                                                         "qty": 12, "batch_no": "API1", "expiry_date": str(in_days(30))})
    assert r.status_code == 201, r.text
    r = client.get("/api/v1/stock/lookup", headers=h, params={"code": "8900000000011", "location_id": world.store.id})
    assert r.json()["stock"]["on_hand"] == 12
    r = client.post("/api/v1/sales", headers=h, json={"location_id": world.store.id,
                                                      "lines": [{"product_id": rice.id, "qty": 2}]})
    assert r.status_code == 201 and r.json()["total"] == 240
    r = client.get("/api/v1/stock/lookup", headers=h, params={"code": "RICE-1", "location_id": world.store.id})
    assert r.json()["stock"]["on_hand"] == 10
    r = client.post("/api/v1/sales", headers=h, json={"location_id": world.store.id,
                                                      "lines": [{"product_id": rice.id, "qty": 50}]})
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    r = client.post("/api/v1/stock/out", headers=h, json={"product_id": rice.id, "location_id": world.store.id,
                                                          "qty": 1, "type": "adjustment", "reason": "test"})
    assert r.status_code == 403
    mv = client.get("/api/v1/stock/movements", headers=h, params={"product_id": rice.id})
    assert mv.json()["total"] == 2


def test_api_batches_buckets(client, auth, world, db):
    rice = world.products[0]
    make_batch(db, rice, world.store, 1, in_days(-1))
    make_batch(db, rice, world.store, 1, in_days(3))
    make_batch(db, rice, world.store, 1, in_days(20))
    make_batch(db, rice, world.store, 1, in_days(200))
    db.commit()
    h = auth("staff")
    got = {b: client.get("/api/v1/stock/batches", headers=h, params={"bucket": b}).json()["total"]
           for b in ("expired", "critical", "warning", "ok")}
    assert got == {"expired": 1, "critical": 1, "warning": 1, "ok": 1}
