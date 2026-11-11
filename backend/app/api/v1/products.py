from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select

from app.core.deps import DB, require
from app.core.errors import Conflict, NotFound
from app.core.pagination import PageParams, page_params
from app.core.timeutil import today
from app.models.catalog import Product, SupplierProduct
from app.models.core import Location, User
from app.models.inventory import Batch, StockMovement
from app.schemas.common import Page
from app.schemas.master import ProductIn, ProductListOut, ProductOut, SupplierProductOut
from app.schemas.stock import BatchOut, MovementOut
from app.services import audit, stock

router = APIRouter(prefix="/products", tags=["products"])
Reader = Annotated[User, Depends(require("products.read"))]
Writer = Annotated[User, Depends(require("products.write"))]

SORTS = {"sku", "name", "selling_price", "cost_price", "on_hand", "available", "abc_class", "category_name"}
TEXT_SORTS = {"sku", "name", "abc_class", "category_name"}


def stock_status(p: Product, lv: dict[str, float]) -> str:
    if lv["on_hand"] <= 0:
        return "out"
    if p.reorder_point is not None and lv["available"] <= p.reorder_point:
        return "low"
    return "ok"


def to_list_out(p: Product, lv: dict[str, float]) -> ProductListOut:
    out = ProductListOut.model_validate(p)
    out.category_name = p.category.name if p.category else None
    out.on_hand, out.on_order, out.available = (round(lv[k], 3) for k in ("on_hand", "on_order", "available"))
    out.stock_status = stock_status(p, lv)
    return out


def batch_out(b: Batch) -> BatchOut:
    o = BatchOut.model_validate(b)
    o.product_name, o.product_sku, o.location_name = b.product.name, b.product.sku, b.location.name
    o.days_to_expiry = (b.expiry_date - today()).days if b.expiry_date else None
    return o


@router.get("", response_model=Page[ProductListOut])
def list_products(
    user: Reader,
    db: DB,
    p: Annotated[PageParams, Depends(page_params)],
    q: str | None = None,
    category_id: int | None = None,
    location_id: int | None = None,
    is_active: bool | None = True,
    is_perishable: bool | None = None,
    abc_class: str | None = None,
    status: str | None = None,  # out | low | ok
) -> dict[str, Any]:
    stmt = select(Product)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like)))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if is_active is not None:
        stmt = stmt.where(Product.is_active.is_(is_active))
    if is_perishable is not None:
        stmt = stmt.where(Product.is_perishable.is_(is_perishable))
    if abc_class:
        stmt = stmt.where(Product.abc_class == abc_class.upper())
    products = list(db.scalars(stmt).unique())
    levels = stock.levels(db, location_id)
    zero = {"on_hand": 0.0, "on_order": 0.0, "available": 0.0}
    rows = [to_list_out(prod, levels.get(prod.id, zero)) for prod in products]
    if status:
        rows = [r for r in rows if r.stock_status == status]
    key = (p.sort or "name").lstrip("-")
    if key not in SORTS:
        key = "name"
    text_key = key in TEXT_SORTS

    def sort_key(r: ProductListOut) -> Any:
        v = getattr(r, key)
        return (v or "").lower() if text_key else (v if v is not None else float("-inf"))

    rows.sort(key=sort_key, reverse=bool(p.sort and p.sort.startswith("-")))
    start = (p.page - 1) * p.page_size
    return {
        "items": rows[start : start + p.page_size],
        "total": len(rows),
        "page": p.page,
        "page_size": p.page_size,
    }


@router.get("/{product_id}")
def product_detail(product_id: int, user: Reader, db: DB) -> dict[str, Any]:
    prod = stock.get_product(db, product_id)
    batches = db.scalars(
        select(Batch)
        .where(Batch.product_id == product_id, Batch.qty_on_hand > 0)
        .order_by(Batch.expiry_date.asc().nulls_last())
    ).unique()
    locations = list(db.scalars(select(Location).order_by(Location.id)))
    per_location = [
        {"location_id": loc.id, "location": loc.name, **stock.position(db, product_id, loc.id)}
        for loc in locations
    ]
    movements = db.scalars(
        select(StockMovement)
        .where(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.desc())
        .limit(50)
    ).unique()
    suppliers = db.scalars(
        select(SupplierProduct)
        .where(SupplierProduct.product_id == product_id)
        .order_by(SupplierProduct.unit_price)
    ).unique()
    base = ProductOut.model_validate(prod)
    base.category_name = prod.category.name if prod.category else None
    lv = stock.position(db, product_id)
    return {
        "product": base,
        "position": lv,
        "stock_status": stock_status(prod, lv),
        "by_location": per_location,
        "batches": [batch_out(b) for b in batches],
        "movements": [MovementOut.model_validate(m) for m in movements],
        "suppliers": [
            SupplierProductOut.model_validate(sp).model_copy(update={"supplier_name": sp.supplier.name})
            for sp in suppliers
        ],
        "calc": prod.calc_json,
    }


def _unique_check(db: DB, body: ProductIn, exclude_id: int | None = None) -> None:
    stmt = select(Product).where(
        or_(
            func.lower(Product.sku) == body.sku.lower(),
            Product.barcode == body.barcode if body.barcode else False,
        )
    )
    for other in db.scalars(stmt).unique():
        if other.id != exclude_id:
            raise Conflict("SKU or barcode already used by another product")


@router.post("", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, user: Writer, db: DB) -> Product:
    _unique_check(db, body)
    prod = Product(**body.model_dump())
    db.add(prod)
    audit.created(db, user, prod)
    db.commit()
    return prod


@router.put("/{product_id}", response_model=ProductOut)
def update_product(product_id: int, body: ProductIn, user: Writer, db: DB) -> Product:
    prod = stock.get_product(db, product_id)
    _unique_check(db, body, exclude_id=product_id)
    audit.apply_update(db, user, prod, body.model_dump())
    db.commit()
    return prod


@router.delete("/{product_id}")
def deactivate_product(product_id: int, user: Writer, db: DB) -> dict[str, str]:
    prod = db.get(Product, product_id)
    if not prod:
        raise NotFound("Product not found")
    audit.apply_update(db, user, prod, {"is_active": False})
    db.commit()
    return {"detail": "Product deactivated"}
