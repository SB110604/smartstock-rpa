from sqlalchemy import func, select

from app.models import Batch, Festival, Product, PurchaseOrder, Sale, Supplier, ThreeWayMatch, User
from app.seed.generator import generate


def test_seed_generates_consistent_dataset(db):
    info = generate(db, log=lambda *_: None, sales_days=150, purchase_days=120)
    assert info["products"] == 80
    assert db.scalar(select(func.count()).select_from(Supplier)) == 10
    assert db.scalar(select(func.count()).select_from(User)) == 5
    states = {s for (s,) in db.execute(select(Supplier.state).distinct())}
    assert "Maharashtra" in states and len(states) >= 4  # CGST/SGST and IGST both exercised
    assert db.scalar(select(func.count()).select_from(Festival)) >= 27
    assert db.scalar(select(func.count()).select_from(Sale)) > 5000
    statuses = {s for (s,) in db.execute(select(PurchaseOrder.status).distinct())}
    assert {"CLOSED", "INVOICED"} <= statuses
    assert db.scalar(select(func.count()).where(ThreeWayMatch.status == "mismatch")) == 2
    skus = [s for (s,) in db.execute(select(Product.sku))]
    assert len(skus) == len(set(skus))
    barcodes = [b for (b,) in db.execute(select(Product.barcode))]
    for code in barcodes:  # valid EAN-13 check digits
        total = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(code[:12]))
        assert (10 - total % 10) % 10 == int(code[12])
    expired = db.scalar(select(func.count()).where(Batch.qty_on_hand > 0, Batch.expiry_date <= func.current_date()))
    assert expired >= 3


def test_seed_is_deterministic(db):
    a = generate(db, log=lambda *_: None, sales_days=60, purchase_days=40)
    totals_a = db.scalar(select(func.sum(Sale.total)))
    generate(db, log=lambda *_: None, sales_days=60, purchase_days=40)
    assert db.scalar(select(func.sum(Sale.total))) == totals_a
    assert a["products"] == 80
