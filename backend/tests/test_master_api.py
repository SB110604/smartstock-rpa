from sqlalchemy import select

from app.models import AuditLog
from app.services.pdfbase import amount_in_words, inr
from tests.factories import in_days, make_batch


def test_product_crud_and_audit(client, auth, db, world):
    h = auth("manager")
    body = {"sku": "TEA-1", "name": "Assam Tea 250g", "cost_price": 110, "selling_price": 140, "gst_rate": 5,
            "barcode": "8901111111111", "pack_size": 12}
    r = client.post("/api/v1/products", headers=h, json=body)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert client.post("/api/v1/products", headers=h, json=body).status_code == 409
    bad = client.post("/api/v1/products", headers=h, json={**body, "sku": "T2", "barcode": None, "gst_rate": 7})
    assert bad.status_code == 422
    r = client.put(f"/api/v1/products/{pid}", headers=h, json={**body, "selling_price": 150})
    assert r.json()["selling_price"] == 150
    log = db.scalars(select(AuditLog).where(AuditLog.entity == "products", AuditLog.entity_id == str(pid))
                     .order_by(AuditLog.id)).all()
    assert [a.action for a in log] == ["create", "update"]
    assert log[1].before_json == {"selling_price": 140} and log[1].after_json == {"selling_price": 150}


def test_product_list_stock_status_and_detail(client, auth, db, world):
    rice, milk = world.products
    rice.reorder_point = 20
    make_batch(db, rice, world.store, 5, in_days(100))
    db.commit()
    h = auth("staff")
    r = client.get("/api/v1/products", headers=h, params={"status": "low"}).json()
    assert [p["sku"] for p in r["items"]] == ["RICE-1"]
    out = client.get("/api/v1/products", headers=h, params={"status": "out"}).json()
    assert [p["sku"] for p in out["items"]] == ["MILK-1"]
    sorted_ = client.get("/api/v1/products", headers=h, params={"sort": "-selling_price"}).json()["items"]
    assert sorted_[0]["sku"] == "RICE-1"
    d = client.get(f"/api/v1/products/{rice.id}", headers=h).json()
    assert d["position"]["on_hand"] == 5 and len(d["batches"]) == 1 and len(d["suppliers"]) == 2
    assert d["suppliers"][0]["unit_price"] == 85  # cheapest first


def test_supplier_validation_and_detail(client, auth, world):
    h = auth("manager")
    bad = client.post("/api/v1/suppliers", headers=h, json={"name": "Bad GST", "gstin": "12345"})
    assert bad.status_code == 422 and "GSTIN" in bad.json()["detail"]
    ok = client.post("/api/v1/suppliers", headers=h, json={"name": "Nashik Fresh", "gstin": "27aaaaa1111a1z1",
                                                           "state": "Maharashtra"})
    assert ok.status_code == 201 and ok.json()["gstin"] == "27AAAAA1111A1Z1"
    lst = client.get("/api/v1/suppliers", headers=h, params={"q": "acme"}).json()
    assert lst["total"] == 1 and lst["items"][0]["products"] == 2
    detail = client.get(f"/api/v1/suppliers/{world.supplier.id}", headers=h).json()
    assert len(detail["prices"]) == 2


def test_users_admin_management(client, auth, world):
    h = auth("admin")
    r = client.post("/api/v1/users", headers=h, json={"name": "New Staff", "email": "new@test.in", "role": "staff",
                                                      "password": "Passw0rd!"})
    assert r.status_code == 201
    dup = client.post("/api/v1/users", headers=h, json={"name": "Dup", "email": "NEW@test.in", "role": "staff",
                                                        "password": "Passw0rd!"})
    assert dup.status_code == 409
    no_link = client.post("/api/v1/users", headers=h, json={"name": "Sup", "email": "s@test.in", "role": "supplier",
                                                            "password": "Passw0rd!"})
    assert no_link.status_code == 422
    me = world.users["admin"].id
    assert client.patch(f"/api/v1/users/{me}", headers=h, json={"is_active": False}).status_code == 422


def test_settings_validation(client, auth, world):
    h = auth("admin")
    r = client.put("/api/v1/settings", headers=h, json={"ordering_cost_S": 650, "service_level": 0.97})
    assert r.status_code == 200 and r.json()["values"]["ordering_cost_S"] == 650
    bad = client.put("/api/v1/settings", headers=h, json={"supplier_weights": {"price": 0.9, "ontime": 0.3,
                                                                               "lead": 0, "quality": 0}})
    assert bad.status_code == 422
    assert client.put("/api/v1/settings", headers=h, json={"nope": 1}).status_code == 422
    pub = client.get("/api/v1/settings/public", headers=auth("staff")).json()
    assert pub["features"]["llm_provider"] == "none"


def test_labels_pdf(client, auth, world, db):
    rice = world.products[0]
    b = make_batch(db, rice, world.store, 3, in_days(30), "LBL1")
    db.commit()
    h = auth("staff")
    r = client.post("/api/v1/labels/products", headers=h, json={"product_ids": [rice.id], "copies": 30})
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.content.count(b"/Type /Page") >= 2
    r = client.post("/api/v1/labels/batches", headers=h, json={"batch_ids": [b.id]})
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_pos_api_with_key(client, auth, db, world):
    rice = world.products[0]
    make_batch(db, rice, world.store, 10, in_days(60))
    db.commit()
    key = client.post("/api/v1/settings/api-keys", headers=auth("admin"),
                      json={"name": "Counter 1", "location_id": world.store.id}).json()["key"]
    body = {"invoice_no": "POS-1", "lines": [{"barcode": "8900000000011", "qty": 3}]}
    assert client.post("/api/v1/integrations/pos/sales", json=body).status_code == 401
    assert client.post("/api/v1/integrations/pos/sales", json=body, headers={"X-API-Key": "bad"}).status_code == 401
    r = client.post("/api/v1/integrations/pos/sales", json=body, headers={"X-API-Key": key})
    assert r.status_code == 201 and r.json()["channel"] == "pos_api" and r.json()["total"] == 360
    dup = client.post("/api/v1/integrations/pos/sales", json=body, headers={"X-API-Key": key})
    assert dup.status_code == 409


def test_audit_endpoint_filters(client, auth, world):
    client.post("/api/v1/categories", headers=auth("manager"), json={"name": "Beverages"})
    r = client.get("/api/v1/audit", headers=auth("admin"), params={"entity": "categories"}).json()
    assert r["total"] == 1 and r["items"][0]["user_name"] == "Manager User"


def test_inr_formatting_and_words():
    assert inr(1234567.5) == "₹12,34,567.50"
    assert inr(999) == "₹999.00"
    assert amount_in_words(125430.5) == "Rupees One Lakh Twenty Five Thousand Four Hundred Thirty and Fifty Paise Only"
    assert amount_in_words(0) == "Rupees Zero Only"
