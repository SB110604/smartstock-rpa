from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import count
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.timeutil import now, today
from app.models import Batch, Category, Location, Product, Supplier, SupplierProduct, User

_seq = count(1)
PASSWORD = "Secret@123"


def uniq(prefix: str) -> str:
    return f"{prefix}{next(_seq)}"


def make_user(db: Session, role: str, **kw: Any) -> User:
    u = User(name=kw.pop("name", f"{role.title()} User"), email=kw.pop("email", f"{uniq(role)}@test.in"),
             password_hash=hash_password(kw.pop("password", PASSWORD)), role=role, **kw)
    db.add(u)
    db.flush()
    return u


def make_location(db: Session, name: str | None = None, type: str = "store") -> Location:
    loc = Location(name=name or uniq("Loc"), type=type)
    db.add(loc)
    db.flush()
    return loc


def make_category(db: Session, name: str | None = None) -> Category:
    c = Category(name=name or uniq("Cat"))
    db.add(c)
    db.flush()
    return c


def make_product(db: Session, **kw: Any) -> Product:
    sku = kw.pop("sku", uniq("SKU-"))
    p = Product(sku=sku, name=kw.pop("name", f"Product {sku}"), cost_price=kw.pop("cost_price", 80.0),
                selling_price=kw.pop("selling_price", 100.0), gst_rate=kw.pop("gst_rate", 5.0),
                unit=kw.pop("unit", "pcs"), **kw)
    db.add(p)
    db.flush()
    return p


def make_supplier(db: Session, **kw: Any) -> Supplier:
    s = Supplier(name=kw.pop("name", uniq("Supplier ")), state=kw.pop("state", "Maharashtra"),
                 email=kw.pop("email", f"{uniq('sup')}@supplier.in"), **kw)
    db.add(s)
    db.flush()
    return s


def make_price(db: Session, supplier: Supplier, product: Product, price: float, lead: int = 3) -> SupplierProduct:
    sp = SupplierProduct(supplier_id=supplier.id, product_id=product.id, unit_price=price, lead_time_days=lead)
    db.add(sp)
    db.flush()
    return sp


def make_batch(db: Session, product: Product, location: Location, qty: float, expiry: date | None = None,
               batch_no: str | None = None, days_old: int = 10, **kw: Any) -> Batch:
    b = Batch(product_id=product.id, location_id=location.id, batch_no=batch_no or uniq("B"), expiry_date=expiry,
              qty_on_hand=qty, cost_price=kw.pop("cost_price", product.cost_price),
              received_at=now() - timedelta(days=days_old), **kw)
    db.add(b)
    db.flush()
    return b


def headers_for(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role, user.token_version)}"}


@dataclass
class World:
    store: Location
    warehouse: Location
    supplier: Supplier
    other_supplier: Supplier
    users: dict[str, User]
    products: list[Product] = field(default_factory=list)


def build_world(db: Session) -> World:
    store = make_location(db, "Test Store", "store")
    warehouse = make_location(db, "Test Warehouse", "warehouse")
    supplier = make_supplier(db, name="Acme Foods", state="Maharashtra", gstin="27ABCDE1234F1Z5")
    other = make_supplier(db, name="Delhi Distributors", state="Delhi", gstin="07ABCDE1234F1Z5")
    users = {
        "admin": make_user(db, "admin", email="admin@test.in"),
        "manager": make_user(db, "manager", email="manager@test.in"),
        "staff": make_user(db, "staff", email="staff@test.in"),
        "supplier": make_user(db, "supplier", email="supplier@test.in", supplier_id=supplier.id),
        "supplier2": make_user(db, "supplier", email="supplier2@test.in", supplier_id=other.id),
    }
    cat = make_category(db, "Staples")
    rice = make_product(db, sku="RICE-1", name="Basmati Rice 1kg", barcode="8900000000011", category_id=cat.id,
                        cost_price=90, selling_price=120, gst_rate=5, pack_size=10, min_order_qty=10)
    milk = make_product(db, sku="MILK-1", name="Toned Milk 500ml", barcode="8900000000028", category_id=cat.id,
                        cost_price=24, selling_price=28, gst_rate=0, is_perishable=True, shelf_life_days=4)
    make_price(db, supplier, rice, 88, lead=4)
    make_price(db, other, rice, 85, lead=7)
    make_price(db, supplier, milk, 23, lead=1)
    db.commit()
    return World(store, warehouse, supplier, other, users, [rice, milk])


def in_days(n: int) -> date:
    return today() + timedelta(days=n)
