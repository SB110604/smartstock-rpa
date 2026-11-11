import io

from openpyxl import load_workbook
from sqlalchemy import select

from app.models import Batch, Product, Sale, SupplierProduct
from app.services import imports

PRODUCTS_CSV = """Item Code,Product Name,Category,GST %,Cost,MRP,Perishable,Shelf Life,Pack
NEW-1,Sugar 1kg,Staples,5,40,48,no,,10
NEW-2,Paneer 200g,Dairy,5,70,90,yes,7,1
BAD-1,Bad Gst,Staples,7,10,12,no,,1
,Missing Sku,Staples,5,10,12,no,,1
NEW-1,Duplicate,Staples,5,40,48,no,,10
RICE-1,Basmati Rice 1kg (updated),Staples,5,91,121,no,,10
"""


def upload(client, h, entity, text, name="f.csv"):
    return client.post("/api/v1/imports/upload", headers=h, data={"entity": entity},
                       files={"file": (name, text.encode() if isinstance(text, str) else text, "text/csv")})


def test_auto_map_matches_aliases_and_fuzzy():
    spec = imports.spec_for("products")
    m = imports.auto_map(["Item Code", "Product Name", "GST %", "Cost", "MRP", "Categry"], spec)
    assert m["sku"] == "Item Code" and m["name"] == "Product Name" and m["gst_rate"] == "GST %"
    assert m["cost_price"] == "Cost" and m["selling_price"] == "MRP"
    assert m["category"] == "Categry"  # fuzzy
    assert m["barcode"] is None


def test_coerce_types():
    assert imports.coerce(imports.F("d", "date"), "05-11-2026").isoformat() == "2026-11-05"
    assert imports.coerce(imports.F("n", "float"), "₹1,250.50") == 1250.5
    assert imports.coerce(imports.F("b", "bool"), "Yes") is True


def test_products_import_preview_and_commit(client, auth, db, world):
    h = auth("manager")
    up = upload(client, h, "products", PRODUCTS_CSV)
    assert up.status_code == 201, up.text
    job = up.json()
    assert job["mapping"]["sku"] == "Item Code" and job["rows"] == 6
    prev = client.post(f"/api/v1/imports/{job['job_id']}/preview", headers=h, json={"mapping": job["mapping"]}).json()
    assert prev["valid"] == 3 and prev["invalid"] == 3
    errors = {r["row"]: " ".join(r["errors"]) for r in prev["error_rows"]}
    assert "gst_rate" in errors[4] and "sku is required" in errors[5] and "duplicate sku" in errors[6]
    res = client.post(f"/api/v1/imports/{job['job_id']}/commit", headers=h, json={"mapping": job["mapping"]}).json()
    assert (res["created"], res["updated"], res["skipped"]) == (2, 1, 3)
    paneer = db.scalar(select(Product).where(Product.sku == "NEW-2"))
    assert paneer.is_perishable and paneer.shelf_life_days == 7 and paneer.category.name == "Dairy"
    assert db.scalar(select(Product).where(Product.sku == "RICE-1")).cost_price == 91
    report = client.get(f"/api/v1/imports/{job['job_id']}/errors.csv", headers=h)
    assert report.status_code == 200 and report.text.count("\n") == 4
    again = client.post(f"/api/v1/imports/{job['job_id']}/commit", headers=h, json={"mapping": job["mapping"]})
    assert again.status_code == 422


def test_preview_requires_required_mappings(client, auth, world):
    h = auth("manager")
    job = upload(client, h, "products", PRODUCTS_CSV).json()
    r = client.post(f"/api/v1/imports/{job['job_id']}/preview", headers=h, json={"mapping": {"sku": "Item Code"}})
    assert r.status_code == 422 and "name" in r.json()["detail"]


def test_supplier_import_validates_gstin(client, auth, world):
    h = auth("manager")
    csv = "name,state,gstin,email\nGood Co,Maharashtra,27AAAAA1111A1Z1,a@b.in\nBad Co,Goa,12345,not-email\n"
    job = upload(client, h, "suppliers", csv).json()
    prev = client.post(f"/api/v1/imports/{job['job_id']}/preview", headers=h, json={"mapping": job["mapping"]}).json()
    assert prev["valid"] == 1
    assert "gstin" in prev["error_rows"][0]["errors"][0] and "email" in prev["error_rows"][0]["errors"][1]


def test_supplier_prices_and_opening_stock(client, auth, db, world):
    h = auth("manager")
    csv = "supplier,sku,price,lead time\nAcme Foods,MILK-1,22.5,2\nAcme Foods,NOPE,1,1\n"
    job = upload(client, h, "supplier_prices", csv).json()
    res = client.post(f"/api/v1/imports/{job['job_id']}/commit", headers=h, json={"mapping": job["mapping"]}).json()
    assert res["updated"] == 1 and res["skipped"] == 1
    sp = db.scalar(select(SupplierProduct).where(SupplierProduct.product_id == world.products[1].id,
                                                 SupplierProduct.supplier_id == world.supplier.id))
    assert sp.unit_price == 22.5 and sp.lead_time_days == 2

    csv = "sku,location,qty,batch,expiry\nRICE-1,Test Store,40,OB1,30-06-2027\nMILK-1,Test Store,5,OB2,\n"
    job = upload(client, h, "opening_stock", csv).json()
    res = client.post(f"/api/v1/imports/{job['job_id']}/commit", headers=h, json={"mapping": job["mapping"]}).json()
    assert res["created"] == 2
    b = db.scalar(select(Batch).where(Batch.batch_no == "OB1"))
    assert b.qty_on_hand == 40 and b.expiry_date.isoformat() == "2027-06-30"


def test_sales_history_import_groups_invoices(client, auth, db, world):
    h = auth("manager")
    csv = "invoice_no,date,sku,qty,unit_price\nH1,01-10-2026,RICE-1,2,120\nH1,01-10-2026,MILK-1,1,28\nH2,02-10-2026,RICE-1,1,\n"
    job = upload(client, h, "sales_history", csv).json()
    res = client.post(f"/api/v1/imports/{job['job_id']}/commit", headers=h, json={"mapping": job["mapping"]}).json()
    assert res["created"] == 3
    h1 = db.scalar(select(Sale).where(Sale.invoice_no == "H1"))
    assert h1.total == 268 and h1.channel == "import"


def test_templates_csv_and_xlsx(client, auth, world):
    h = auth("manager")
    r = client.get("/api/v1/imports/templates/opening_stock", headers=h)
    assert r.status_code == 200 and r.text.startswith("﻿sku,location,qty")
    r = client.get("/api/v1/imports/templates/products", headers=h, params={"fmt": "xlsx"})
    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws.cell(1, 1).value == "sku" and ws.max_row == 2
    # the template itself imports cleanly
    job = upload(client, h, "products", r.content, "products_template.xlsx").json()
    prev = client.post(f"/api/v1/imports/{job['job_id']}/preview", headers=h, json={"mapping": job["mapping"]}).json()
    assert prev["valid"] == 1, prev


def test_rejects_unknown_file_type(client, auth, world):
    r = upload(client, auth("manager"), "products", "x", "notes.pdf")
    assert r.status_code == 422
