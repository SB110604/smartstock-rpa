from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import llm
from app.assistant import engine
from app.core.timeutil import today
from app.ml import forecast
from app.ml import learning as ml_learning
from app.models import (
    Alert,
    ChatMessage,
    Forecast,
    ForecastAccuracy,
    ModelRegistry,
    Product,
    PurchaseRequest,
    SupplierProduct,
    SupplierQuote,
)
from app.services import ocr, quote_reader, simulator
from tests.factories import in_days, make_batch, make_product

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def shop(world, db):
    rice, milk = world.products
    make_batch(db, rice, world.store, 40, in_days(200))
    make_batch(db, milk, world.store, 6, in_days(3))
    sugar = make_product(db, sku="SUG-1", name="Sugar 1kg", cost_price=41, selling_price=48, unit="kg", pack_size=25)
    db.add(SupplierProduct(supplier_id=world.supplier.id, product_id=sugar.id, unit_price=40, lead_time_days=2))
    db.commit()
    return world


# ------------------------------------------------------------------ assistant (LLM_PROVIDER=none)

@pytest.mark.parametrize(("question", "tool", "expect"), [
    ("How much rice is left?", "stock_level", "Basmati Rice 1kg: 40"),
    ("Which items expire this week?", "expiring_items", "Toned Milk 500ml"),
    ("Show pending approvals", "pending_approvals", "no purchase requests waiting"),
    ("Best supplier for sugar?", "best_supplier", "Best supplier for Sugar 1kg: Acme Foods"),
    ("What is the forecast for milk?", "demand_forecast", "No forecast is available"),
    ("Sales this week", "sales_summary", "Last 7 days"),
    ("Show low stock items", "low_stock", "need attention"),
])
def test_assistant_answers_examples_without_llm(db, shop, question, tool, expect):
    a = engine.answer(db, shop.users["manager"], question)
    assert a.mode == "rules"
    assert a.tool_calls[0]["name"] == tool
    assert expect.lower() in a.reply.lower(), a.reply


def test_assistant_drafts_purchase_request_only(db, shop):
    a = engine.answer(db, shop.users["manager"], "Create a purchase request for 50 kg sugar")
    pr = db.scalar(select(PurchaseRequest).order_by(PurchaseRequest.id.desc()))
    assert pr.status == "DRAFT" and pr.suggested_qty == 50 and pr.product.name == "Sugar 1kg"
    assert f"#{pr.id}" in a.reply and "DRAFT" in a.reply
    assert db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant").order_by(ChatMessage.id.desc())).tool_calls_json


def test_assistant_respects_roles(db, shop):
    staff = engine.answer(db, shop.users["staff"], "Create a purchase request for 10 kg sugar")
    assert "permission" in staff.reply.lower()
    sup = engine.answer(db, shop.users["supplier"], "Best supplier for sugar?")
    assert "permission" in sup.reply.lower()
    assert engine.answer(db, shop.users["supplier"], "show my open purchase orders").tool_calls[0]["name"] == "open_orders"


def test_assistant_help_and_missing_qty(db, shop):
    assert "I can answer" in engine.answer(db, shop.users["manager"], "hello").reply
    assert "How much should I order" in engine.answer(db, shop.users["manager"], "create a purchase request for sugar").reply


class FakeProvider(llm.OpenAIProvider):
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def chat(self, system, messages, tools=None):
        if self.fail:
            raise llm.LLMError("down")
        self.calls += 1
        if self.calls == 1:
            return llm.Reply("", [llm.ToolCall("c1", "stock_level", {"product": "rice"})],
                             {"role": "assistant", "content": None, "tool_calls": []})
        assert "Basmati Rice 1kg" in messages[-1]["content"]  # tool output was fed back
        return llm.Reply("You have 40 packs of basmati rice.", [], {})


def test_assistant_llm_tool_loop_and_fallback(db, shop, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr(llm, "get_provider", lambda: fake)
    a = engine.answer(db, shop.users["manager"], "rice?")
    assert a.mode == "fake" and a.reply == "You have 40 packs of basmati rice." and a.tool_calls[0]["name"] == "stock_level"
    monkeypatch.setattr(llm, "get_provider", lambda: FakeProvider(fail=True))
    b = engine.answer(db, shop.users["manager"], "How much rice is left?")
    assert b.mode == "rules" and "40" in b.reply


def test_assistant_api(client, auth, shop):
    r = client.post("/api/v1/assistant/chat", headers=auth("manager"), json={"message": "How much rice is left?"})
    assert r.status_code == 200 and "40" in r.json()["reply"]
    assert len(client.get("/api/v1/assistant/history", headers=auth("manager")).json()) == 2
    client.delete("/api/v1/assistant/history", headers=auth("manager"))
    assert client.get("/api/v1/assistant/history", headers=auth("manager")).json() == []
    assert client.get("/api/v1/assistant/status", headers=auth("staff")).json()["llm"]["provider"] == "none"


# ------------------------------------------------------------------ OCR

OCR_TEXT = """AGARWAL WHOLESALE TRADERS
GSTIN: 27ABCDE1234F1Z5
TAX INVOICE
Invoice No: AWT/26/0457                  Date: 02-11-2026
Item                        HSN    Qty Unit     Rate      Amount
Basmati Rice 1kg            1006    20 pack   128.00     2560.00
Toned Milk 500ml            0401    50 pcs     24.00     1200.00
Mystery Widget              9999     2 pcs     10.00       20.00
Sub Total     3780.00
Grand Total   3969.00
"""


def test_ocr_parser_and_matching(db, shop):
    parsed = ocr.parse_text(OCR_TEXT)
    assert parsed["invoice_no"] == "AWT/26/0457" and parsed["invoice_date"] == "2026-11-02"
    assert parsed["gstins"] == ["27ABCDE1234F1Z5"] and parsed["total"] == 3969.0
    assert [(ln["qty"], ln["unit_price"], ln["amount"]) for ln in parsed["lines"]] == [(20, 128, 2560), (50, 24, 1200), (2, 10, 20)]
    m = ocr.match(db, parsed, OCR_TEXT)
    assert m["supplier"]["name"] == "Acme Foods"  # matched by GSTIN
    lines = m["lines"]
    assert lines[0]["product_name"] == "Basmati Rice 1kg" and lines[0]["confidence"] >= 90
    assert lines[1]["product_name"] == "Toned Milk 500ml"
    assert lines[2]["product_id"] is None and lines[2]["confidence"] < lines[0]["confidence"]


def test_sample_bill_fixture_exists_and_is_generated():
    from tests.fixtures.make_sample_bill import LINES, make

    path = FIXTURES / "sample_bill.png"
    assert path.exists() and path.stat().st_size > 10_000
    assert len(LINES) == 4
    assert make(FIXTURES / "sample_bill.png").exists()


@pytest.mark.skipif(not ocr.available(), reason="Tesseract is not installed on this machine (it is in the Docker image)")
def test_ocr_end_to_end_prefills_invoice_from_fixture(client, auth, db, shop):
    for name, cost in (("Toor Dal 1kg", 128), ("Tata Salt 1kg", 22), ("Fortune Sunflower Oil 1L", 128)):
        make_product(db, name=name, cost_price=cost, selling_price=cost * 1.2)
    db.commit()
    with open(FIXTURES / "sample_bill.png", "rb") as fh:
        r = client.post("/api/v1/ocr/invoice", headers=auth("manager"), files={"file": ("sample_bill.png", fh, "image/png")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["invoice_no"] == "AWT/26/0457"
    names = [ln["product_name"] for ln in body["lines"]]
    assert {"Toor Dal 1kg", "Sugar 1kg", "Tata Salt 1kg", "Fortune Sunflower Oil 1L"} <= set(names)
    assert all(ln["confidence"] > 70 for ln in body["lines"])
    assert db.scalar(select(PurchaseRequest)) is None  # nothing saved


def test_ocr_unavailable_returns_503(client, auth, shop, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    r = client.post("/api/v1/ocr/invoice", headers=auth("manager"), files={"file": ("x.png", b"123", "image/png")})
    assert r.status_code == 503 and r.json()["code"] == "ocr_unavailable"


# ------------------------------------------------------------------ learning

def test_retrain_promotes_only_better_models(db, shop, monkeypatch):
    from app.seed.generator import generate

    generate(db, log=lambda *_: None, sales_days=150, purchase_days=60)
    first = ml_learning.retrain(db)
    assert first["promoted"] and first["incumbent"] is None
    monkeypatch.setattr(ml_learning, "evaluate_artifact", lambda *a, **k: 1.0)  # incumbent looks unbeatable
    second = ml_learning.retrain(db)
    assert not second["promoted"] and "kept incumbent" in second["note"]
    actives = db.scalars(select(ModelRegistry).where(ModelRegistry.name == forecast.MODEL_NAME, ModelRegistry.is_active.is_(True))).all()
    assert len(actives) == 1 and actives[0].version == first["challenger"]
    monkeypatch.setattr(ml_learning, "evaluate_artifact", lambda *a, **k: 999.0)
    third = ml_learning.retrain(db)
    assert third["promoted"]
    assert ml_learning.backfill_history(db, weeks=2) > 0
    assert db.scalar(select(ForecastAccuracy)) is not None


def test_accuracy_and_drift_alert(db, shop):
    rice = shop.products[0]
    db.add(ModelRegistry(name=forecast.MODEL_NAME, version="vtest", trained_at=today(), metrics={"mape": 20.0}, is_active=True))
    for k in range(1, 15):
        db.add(ForecastAccuracy(date=today() - timedelta(days=k), mape=40.0, products=10, model_version="vtest"))
    db.add(Forecast(product_id=rice.id, date=today() - timedelta(days=1), predicted_qty=5, lower=1, upper=9, model_name="hgb",
                    model_version="vtest"))
    db.flush()
    status = ml_learning.drift_status(db)
    assert status["drift"] and status["threshold"] == 30.0
    from app.agents import orchestrator

    out = orchestrator.run_agent(db, "learning")
    assert out["runs"][0]["status"] == "success", out["runs"][0]
    assert db.scalar(select(Alert).where(Alert.type == "forecast_drift", Alert.status == "open"))


def test_performance_api(client, auth, db, world):
    from app.workflow import purchasing

    db.add_all([__import__("app.models", fromlist=["ApprovalRule"]).ApprovalRule(min_amount=0, max_amount=None,
                                                                                approver_role="manager")])
    db.flush()
    from app.workflow import approvals

    pr = purchasing.create_request(db, product_id=world.products[0].id, location_id=world.store.id, qty=100,
                                   supplier_id=world.supplier.id, user=None, created_by="agent")
    approvals.decide(db, pr, world.users["manager"], "approve", final_qty=120, create_po=False)
    db.commit()
    r = client.get("/api/v1/insights/performance", headers=auth("manager")).json()
    assert r["totals"]["suggestions"] == 1 and r["totals"]["acceptance_pct"] == 100 and r["totals"]["avg_correction"] == 1.2


# ------------------------------------------------------------------ simulator

def test_simulator_reacts_to_assumptions(db, shop):
    rice = shop.products[0]
    for k in range(30):
        db.add(Forecast(product_id=rice.id, date=today() + timedelta(days=k), predicted_qty=10, lower=5, upper=15,
                        model_name="hgb", model_version="v"))
    db.flush()
    base = simulator.simulate(db, product_ids=[rice.id])["products"][0]
    more = simulator.simulate(db, product_ids=[rice.id], demand_change_pct=50, lead_time_change_days=3, service_level=0.99)
    row = more["products"][0]
    assert row["new"]["rop"] > base["new"]["rop"] and row["new"]["eoq"] > base["new"]["eoq"]
    assert row["new"]["lead_days"] == base["new"]["lead_days"] + 3
    assert row["current"]["rop"] == base["current"]["rop"]
    gone = simulator.simulate(db, product_ids=[rice.id], unavailable_supplier_id=shop.supplier.id)["products"][0]
    assert gone["supplier"] == "Delhi Distributors" and gone["supplier_changed"]
    assert db.scalar(select(Product).where(Product.id == rice.id)).reorder_point is None  # nothing saved


def test_simulator_api_permissions(client, auth, shop):
    assert client.post("/api/v1/simulator", headers=auth("staff"), json={}).status_code == 403
    assert client.post("/api/v1/simulator", headers=auth("manager"), json={"demand_change_pct": 20}).status_code == 200


# ------------------------------------------------------------------ RFQs + email quotes

def test_rfq_full_flow(client, auth, db, shop):
    rice = shop.products[0]
    mgr, s1, s2 = auth("manager"), auth("supplier"), auth("supplier2")
    r = client.post("/api/v1/rfqs", headers=mgr, json={"title": "Diwali rice", "items": [{"product_id": rice.id, "qty": 200}],
                                                        "supplier_ids": [shop.supplier.id]})
    assert r.status_code == 201
    rfq = r.json()
    assert client.get(f"/api/v1/portal/rfqs/{rfq['id']}", headers=s2).status_code == 403
    item = rfq["items"][0]["id"]
    assert client.get("/api/v1/portal/summary", headers=s1).json()["rfqs_awaiting"] == 1
    q = client.post(f"/api/v1/portal/rfqs/{rfq['id']}/quotes", headers=s1,
                    json={"quotes": [{"rfq_item_id": item, "unit_price": 82, "lead_time_days": 3}]})
    assert q.status_code == 200 and q.json()["items"][0]["my_quote"]["unit_price"] == 82
    detail = client.get(f"/api/v1/rfqs/{rfq['id']}", headers=mgr).json()
    quote = detail["comparison"][0]["quotes"][0]
    assert quote["saving_pct"] == pytest.approx((85 - 82) / 85 * 100, abs=0.1)
    assert client.post(f"/api/v1/quotes/{quote['id']}/use", headers=mgr).json()["status"] == "accepted"
    sp = db.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == shop.supplier.id, SupplierProduct.product_id == rice.id))
    assert sp.unit_price == 82 and sp.lead_time_days == 3
    assert client.get(f"/api/v1/rfqs/{rfq['id']}", headers=mgr).json()["status"] == "AWARDED"


def test_email_quote_parser_and_ingest(db, shop):
    body = "Dear sir,\nNew rates from 1st Nov:\n- Basmati Rice 1kg: Rs 86 per pack, delivery 3 days\n- Toned Milk 500ml - 23.50\nThanks"
    parsed = quote_reader.parse_quote_text(db, body)
    assert [(p["product"], p["unit_price"], p["lead_time_days"]) for p in parsed] == [
        ("Basmati Rice 1kg", 86.0, 3), ("Toned Milk 500ml", 23.5, None)]
    quotes = quote_reader.ingest(db, shop.supplier.email.upper(), "Revised rates", body)
    assert len(quotes) == 2 and all(q.status == "pending_review" and q.source == "email" for q in quotes)
    assert quote_reader.ingest(db, "stranger@nowhere.in", "x", body) == []
    assert quote_reader.fetch(db) == {"skipped": 1}  # IMAP not configured → hidden/no-op
    assert db.scalar(select(SupplierQuote).where(SupplierQuote.source == "email")) is not None
