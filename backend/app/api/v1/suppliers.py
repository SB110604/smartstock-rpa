from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select

from app.core.deps import DB, require
from app.core.errors import Conflict, NotFound
from app.core.pagination import PageParams, apply_sort, page_params, paginate
from app.models.ai import SupplierScore
from app.models.catalog import Supplier, SupplierProduct
from app.models.core import User
from app.models.purchasing import PurchaseOrder
from app.schemas.common import Page
from app.schemas.master import SupplierIn, SupplierListOut, SupplierOut, SupplierProductIn, SupplierProductOut
from app.services import audit

router = APIRouter(tags=["suppliers"])
Reader = Annotated[User, Depends(require("suppliers.read"))]
Writer = Annotated[User, Depends(require("suppliers.write"))]


def latest_scores(db: DB) -> dict[int, SupplierScore]:
    sub = (
        select(SupplierScore.supplier_id, func.max(SupplierScore.computed_at).label("m"))
        .group_by(SupplierScore.supplier_id)
        .subquery()
    )
    rows = db.scalars(
        select(SupplierScore).join(
            sub, (SupplierScore.supplier_id == sub.c.supplier_id) & (SupplierScore.computed_at == sub.c.m)
        )
    )
    return {s.supplier_id: s for s in rows}


@router.get("/suppliers", response_model=Page[SupplierListOut])
def list_suppliers(
    user: Reader,
    db: DB,
    p: Annotated[PageParams, Depends(page_params)],
    q: str | None = None,
    state: str | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    stmt = select(Supplier)
    if q:
        stmt = stmt.where(
            or_(
                Supplier.name.ilike(f"%{q}%"),
                Supplier.contact_name.ilike(f"%{q}%"),
                Supplier.gstin.ilike(f"%{q}%"),
            )
        )
    if state:
        stmt = stmt.where(Supplier.state == state)
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active.is_(is_active))
    stmt = apply_sort(stmt, p.sort, {"name": Supplier.name, "state": Supplier.state}, Supplier.name)
    scores = latest_scores(db)
    counts = dict(
        db.execute(
            select(SupplierProduct.supplier_id, func.count()).group_by(SupplierProduct.supplier_id)
        ).all()
    )

    def out(s: Supplier) -> SupplierListOut:
        o = SupplierListOut.model_validate(s)
        sc = scores.get(s.id)
        o.score = round(sc.total_score, 1) if sc else None
        o.on_time_pct = round(sc.on_time_pct, 1) if sc else None
        o.products = counts.get(s.id, 0)
        return o

    return paginate(db, stmt, p, out)


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(body: SupplierIn, user: Writer, db: DB) -> Supplier:
    if db.scalar(select(Supplier.id).where(func.lower(Supplier.name) == body.name.lower())):
        raise Conflict("A supplier with this name already exists")
    sup = Supplier(**body.model_dump())
    db.add(sup)
    audit.created(db, user, sup)
    db.commit()
    return sup


def get_supplier(db: DB, supplier_id: int) -> Supplier:
    sup = db.get(Supplier, supplier_id)
    if not sup:
        raise NotFound("Supplier not found")
    return sup


@router.get("/suppliers/{supplier_id}")
def supplier_detail(supplier_id: int, user: Reader, db: DB) -> dict[str, Any]:
    sup = get_supplier(db, supplier_id)
    prices = db.scalars(select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id)).unique()
    pos = db.scalars(
        select(PurchaseOrder)
        .where(PurchaseOrder.supplier_id == supplier_id)
        .order_by(PurchaseOrder.order_date.desc())
        .limit(100)
    ).unique()
    history = list(
        db.scalars(
            select(SupplierScore)
            .where(SupplierScore.supplier_id == supplier_id)
            .order_by(SupplierScore.computed_at.desc())
            .limit(30)
        )
    )
    score = history[0] if history else None
    return {
        "supplier": SupplierOut.model_validate(sup),
        "score": None
        if not score
        else {
            "total_score": score.total_score,
            "price_score": score.price_score,
            "on_time_pct": score.on_time_pct,
            "lead_score": score.lead_score,
            "quality_score": score.quality_score,
            "reject_pct": score.reject_pct,
            "avg_lead_days": score.avg_lead_days,
            "computed_at": score.computed_at,
            "orders_considered": score.orders_considered,
        },
        "score_history": [
            {"computed_at": s.computed_at, "total_score": s.total_score, "on_time_pct": s.on_time_pct}
            for s in reversed(history)
        ],
        "prices": [
            SupplierProductOut.model_validate(sp).model_copy(
                update={"product_name": sp.product.name, "product_sku": sp.product.sku}
            )
            for sp in prices
        ],
        "purchase_orders": [
            {
                "id": po.id,
                "po_no": po.po_no,
                "status": po.status,
                "order_date": po.order_date,
                "expected_date": po.expected_date,
                "delivered_at": po.delivered_at,
                "total": po.total,
            }
            for po in pos
        ],
    }


@router.put("/suppliers/{supplier_id}", response_model=SupplierOut)
def update_supplier(supplier_id: int, body: SupplierIn, user: Writer, db: DB) -> Supplier:
    sup = get_supplier(db, supplier_id)
    other = db.scalar(
        select(Supplier).where(func.lower(Supplier.name) == body.name.lower(), Supplier.id != supplier_id)
    )
    if other:
        raise Conflict("A supplier with this name already exists")
    audit.apply_update(db, user, sup, body.model_dump())
    db.commit()
    return sup


@router.delete("/suppliers/{supplier_id}")
def deactivate_supplier(supplier_id: int, user: Writer, db: DB) -> dict[str, str]:
    sup = get_supplier(db, supplier_id)
    audit.apply_update(db, user, sup, {"is_active": False})
    db.commit()
    return {"detail": "Supplier deactivated"}


@router.get("/supplier-products", response_model=list[SupplierProductOut])
def list_supplier_products(
    user: Reader, db: DB, product_id: int | None = None, supplier_id: int | None = None
) -> list[SupplierProductOut]:
    stmt = select(SupplierProduct)
    if product_id:
        stmt = stmt.where(SupplierProduct.product_id == product_id)
    if supplier_id:
        stmt = stmt.where(SupplierProduct.supplier_id == supplier_id)
    return [
        SupplierProductOut.model_validate(sp).model_copy(
            update={
                "supplier_name": sp.supplier.name,
                "product_name": sp.product.name,
                "product_sku": sp.product.sku,
            }
        )
        for sp in db.scalars(stmt.order_by(SupplierProduct.unit_price)).unique()
    ]


@router.post("/supplier-products", response_model=SupplierProductOut, status_code=201)
def upsert_supplier_product(body: SupplierProductIn, user: Writer, db: DB) -> SupplierProduct:
    get_supplier(db, body.supplier_id)
    sp = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == body.supplier_id, SupplierProduct.product_id == body.product_id
        )
    )
    if sp:
        audit.apply_update(db, user, sp, body.model_dump())
    else:
        sp = SupplierProduct(**body.model_dump())
        db.add(sp)
        audit.created(db, user, sp)
    db.commit()
    return sp


@router.delete("/supplier-products/{sp_id}")
def delete_supplier_product(sp_id: int, user: Writer, db: DB) -> dict[str, str]:
    sp = db.get(SupplierProduct, sp_id)
    if not sp:
        raise NotFound("Price entry not found")
    audit.deleted(db, user, sp)
    db.delete(sp)
    db.commit()
    return {"detail": "Price entry removed"}
