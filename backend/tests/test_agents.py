from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.agents import orchestrator
from app.agents.base import Agent, AgentContext, execute
from app.core.timeutil import now, today
from app.ml import anomaly, forecast
from app.models import (
    AgentRun,
    Alert,
    AuditLog,
    Batch,
    PoLine,
    Product,
    PurchaseOrder,
    PurchaseRequest,
    StockMovement,
    SupplierScore,
    User,
)
from app.seed.generator import generate
from app.services import supplier_scoring
from tests.factories import headers_for, in_days, make_batch


@pytest.fixture()
def seeded(db):
    generate(db, log=lambda *_: None, sales_days=150, purchase_days=120)
    return db


def test_pipeline_on_seed_data_creates_explained_requests_and_alerts(seeded):
    db = seeded
    result = orchestrator.run_pipeline(db, "seed")
    statuses = {r["agent"]: r["status"] for r in result["runs"]}
    assert list(statuses) == ["stock_monitor", "expiry", "decision", "supplier", "auto_order", "tracking", "anomaly"]
    assert all(s == "success" for s in statuses.values()), result
    assert db.scalar(select(func.count()).select_from(AgentRun)) == 7
    prs = db.scalars(select(PurchaseRequest).where(PurchaseRequest.created_by == "agent",
                                                   PurchaseRequest.created_at >= now() - timedelta(minutes=10))).all()
    assert prs, "expected AI purchase requests"
    for pr in prs:
        assert pr.reason_text.startswith("Forecast ") and "Best supplier:" in pr.reason_text
        rj = pr.reason_json
        assert {"reorder_point", "safety_stock", "eoq", "order_qty", "lead_days"} <= rj.keys()
        assert rj["supplier"]["breakdown"].keys() == {"price", "on_time", "lead", "quality"}
        assert pr.suggested_qty % pr.product.pack_size == 0 or pr.suggested_qty == pr.product.min_order_qty
    with_rop = db.scalar(select(func.count()).select_from(Product).where(Product.reorder_point.is_not(None)))
    assert with_rop == 80
    types = {t for (t,) in db.execute(select(Alert.type).distinct())}
    assert {"expired", "dead_stock", "anomaly", "out_of_stock"} <= types
    expired = db.scalars(select(Batch).where(Batch.expiry_date <= today(), Batch.qty_on_hand > 0)).all()
    assert expired and all(b.is_blocked for b in expired)  # expiry agent blocks expired stock from sale
    assert db.scalar(select(func.count()).select_from(SupplierScore)) >= 10
    # running again does not duplicate open requests or alerts
    n_prs, n_alerts = db.scalar(select(func.count()).select_from(PurchaseRequest)), db.scalar(select(func.count()).select_from(Alert))
    orchestrator.run_pipeline(db, "schedule")
    assert db.scalar(select(func.count()).select_from(PurchaseRequest)) == n_prs
    assert db.scalar(select(func.count()).select_from(Alert)) <= n_alerts + 2


def test_forecast_training_holdout_and_registry(seeded):
    db = seeded
    t = forecast.train(db)
    assert t.metrics["holdout_days"] == 28 and t.metrics["mape_model"] is not None
    assert t.metrics["products_model"] + t.metrics["products_baseline"] == 80
    assert set(t.choice.values()) <= {"hgb", "ma28"}
    reg = forecast.save(db, t, activate=True)
    n = forecast.write_forecasts(db, reg, forecast.load(reg))
    assert n == 80 * 30
    fc = forecast.forecasts_for(db, db.scalar(select(Product.id)))
    assert len(fc) == 30 and all(f.lower <= f.predicted_qty <= f.upper for f in fc)


def test_supplier_scores_follow_weights(world, db):
    # Acme (Maharashtra) 88 / lead 4, Delhi 85 / lead 7 for rice
    rice = world.products[0]
    for sup, lead, late in ((world.supplier, 3, False), (world.other_supplier, 7, True)):
        for k in range(4):
            od = today() - timedelta(days=40 + 7 * k)
            po = PurchaseOrder(po_no=f"PO-T-{sup.id}-{k}", supplier_id=sup.id, location_id=world.store.id, status="CLOSED",
                               order_date=od, expected_date=od + timedelta(days=lead),
                               delivered_at=now() - timedelta(days=40 + 7 * k) + timedelta(days=lead + (3 if late else 0)))
            po.lines.append(PoLine(product_id=rice.id, qty=10, unit_price=88, received_qty=10 if not late else 8,
                                   damaged_qty=0 if not late else 2))
            db.add(po)
    db.flush()
    stats = supplier_scoring.delivery_stats(db)
    assert stats[world.supplier.id].on_time_pct == 100 and stats[world.other_supplier.id].on_time_pct == 0
    assert stats[world.other_supplier.id].reject_pct == pytest.approx(20)
    choice = supplier_scoring.rank_for_product(db, rice.id, stats)
    assert choice.supplier_id == world.supplier.id  # reliable beats 3.5% cheaper
    assert choice.breakdown["on_time"] == 100 and choice.breakdown["price"] == pytest.approx(100 * 85 / 88, abs=0.1)
    expected = 0.35 * choice.breakdown["price"] + 0.30 * 100 + 0.20 * 100 + 0.15 * 100
    assert choice.score == pytest.approx(expected, abs=0.2)
    scores = {s.supplier_id: s for s in supplier_scoring.compute_scores(db)}
    assert scores[world.supplier.id].total_score > scores[world.other_supplier.id].total_score


def test_anomaly_rules(world, db):
    rice = world.products[0]
    staff = world.users["staff"]
    for q in (-1, 1, -2, 1, -1, 2):
        db.add(StockMovement(product_id=rice.id, location_id=world.store.id, type="adjustment", qty=q, unit_cost=90,
                             reference_type="adjustment", user_id=staff.id, created_at=now() - timedelta(days=60)))
    db.add(StockMovement(product_id=rice.id, location_id=world.store.id, type="adjustment", qty=-40, unit_cost=90,
                         reference_type="adjustment", user_id=staff.id, created_at=now() - timedelta(days=1)))
    for _ in range(4):
        db.add(StockMovement(product_id=rice.id, location_id=world.store.id, type="adjustment", qty=-1, unit_cost=90,
                             reference_type="adjustment", user_id=staff.id, created_at=now() - timedelta(days=2)))
    db.add(AuditLog(user_id=staff.id, action="negative_stock_attempt", entity="products", entity_id=str(rice.id),
                    after_json={"requested": 5}))
    db.add(AuditLog(user_id=world.users["manager"].id, action="update", entity="products", entity_id=str(rice.id),
                    before_json={"cost_price": 90}, after_json={"cost_price": 120}))
    db.flush()
    rules = {f.rule for f in anomaly.rule_checks(db)}
    assert {"big_adjustment", "negative_stock", "cost_change", "repeated_corrections"} <= rules
    big = next(f for f in anomaly.big_adjustments(db))
    assert big.severity == "critical" and "beyond 3σ" in big.message and rice.name in big.message


def test_expiry_agent_blocks_and_suggests(world, db):
    milk = world.products[1]
    old = make_batch(db, milk, world.store, 12, in_days(-1), "OLDMILK")
    soon = make_batch(db, milk, world.store, 30, in_days(2), "SOONMILK")
    db.commit()
    result = orchestrator.run_agent(db, "expiry")
    assert result["runs"][-1]["status"] == "success"
    assert old.is_blocked and not soon.is_blocked
    a = db.scalar(select(Alert).where(Alert.type == "expired"))
    assert "write_off" in a.data_json["actions"]
    crit = db.scalar(select(Alert).where(Alert.type == "expiry_critical"))
    assert "30% markdown" in crit.message
    soon.markdown_pct = 30
    db.commit()
    orchestrator.run_agent(db, "expiry")
    db.refresh(crit)
    assert crit.status == "resolved"


def test_failing_agent_does_not_stop_others(db, world):
    class Boom(Agent):
        name = "boom"

        def run(self, ctx: AgentContext):
            raise RuntimeError("kaput")

    ctx = AgentContext(db=db, triggered_by="manual")
    run, result = execute(Boom(), ctx)
    assert run.status == "failed" and "kaput" in run.error and result is None
    run2, result2 = execute(orchestrator.AGENTS["tracking"], ctx)
    assert run2.status == "success" and result2 is not None


def test_agents_api_permissions_and_run_now(client, auth, world):
    assert client.get("/api/v1/agents", headers=auth("staff")).status_code == 403
    lst = client.get("/api/v1/agents", headers=auth("manager")).json()
    assert {a["name"] for a in lst} >= {"stock_monitor", "expiry", "decision", "supplier", "auto_order", "tracking", "anomaly"}
    assert client.post("/api/v1/agents/tracking/run", headers=auth("staff")).status_code == 403
    assert client.post("/api/v1/agents/learning/run", headers=auth("manager")).status_code == 403
    r = client.post("/api/v1/agents/tracking/run", headers=auth("manager"))
    assert r.status_code == 200 and r.json()["runs"][0]["status"] == "success"
    assert client.post("/api/v1/agents/nope/run", headers=auth("admin")).status_code == 404
    runs = client.get("/api/v1/agent-runs", headers=auth("manager")).json()
    assert runs["total"] >= 1


def test_run_now_runs_dependencies(seeded):
    out = orchestrator.run_agent(seeded, "auto_order")
    assert [r["agent"] for r in out["runs"]] == ["decision", "supplier", "auto_order"]
    assert all(r["status"] == "success" for r in out["runs"])


def test_insights_endpoints(client, seeded):
    orchestrator.run_pipeline(seeded, "seed")
    seeded.commit()
    hh = headers_for(seeded.scalar(select(User).where(User.email == "manager@demo.in")))
    pid = seeded.scalar(select(Product.id).where(Product.name == "Toor Dal 1kg"))
    f = client.get(f"/api/v1/products/{pid}/forecast", headers=hh).json()
    assert len(f["forecast"]) == 30 and len(f["actual"]) == 60 and f["model_version"]
    m = client.get("/api/v1/insights/abc-xyz", headers=hh).json()
    assert sum(c["count"] for c in m["cells"].values()) == 80
    assert client.get("/api/v1/insights/dead-stock", headers=hh).json()
    assert client.get("/api/v1/models", headers=hh).json()[0]["name"] in ("demand_forecast", "movement_anomaly")
    e = client.get("/api/v1/expiry", headers=hh).json()
    assert e["totals"]["expired"]["batches"] >= 1 and e["groups"]["critical"]
