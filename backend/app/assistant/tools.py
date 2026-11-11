"""Assistant tools (spec 7.8). Read-only queries + one `draft_purchase_request` that only creates a DRAFT.

Every tool checks the caller's permission; the LLM (if any) can only call these functions — it never writes SQL."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from rapidfuzz import fuzz, process, utils
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permissions import allowed
from app.core.timeutil import now, today
from app.llm import Tool
from app.ml import forecast
from app.models.catalog import Product
from app.models.core import Location, Role, User
from app.models.inventory import Batch, Sale, SaleLine
from app.models.purchasing import PurchaseOrder, PurchaseRequest
from app.services import stock, supplier_scoring
from app.workflow import approvals, purchasing
from app.workflow.machines import PO, PR


class ToolError(Exception):
    pass


@dataclass
class ToolSpec:
    tool: Tool
    permission: str | tuple[str, ...]
    handler: Callable[[Session, User, dict[str, Any]], dict[str, Any]]


# ------------------------------------------------------------------ product resolution

def resolve_products(db: Session, text: str, limit: int = 6) -> list[Product]:
    """Word match first ('rice' → every rice product), then fuzzy match on names/SKUs."""
    q = (text or "").strip().lower()
    if not q:
        return []
    products = list(db.scalars(select(Product).where(Product.is_active.is_(True))).unique())
    words = [w for w in re.findall(r"[a-z0-9]+", q) if len(w) > 2]
    exact = [p for p in products if p.sku.lower() == q or (p.barcode and p.barcode == q)]
    if exact:
        return exact
    if words:
        hits = [p for p in products if all(re.search(rf"\b{re.escape(w)}", p.name.lower()) for w in words)]
        if hits:
            return hits[:limit]
    best = process.extract(q, {p.id: p.name for p in products}, scorer=fuzz.WRatio, processor=utils.default_process,
                           limit=limit)
    top = [b for b in best if b[1] >= 70]
    if not top:
        return []
    cutoff = top[0][1] - 8
    by_id = {p.id: p for p in products}
    return [by_id[b[2]] for b in top if b[1] >= cutoff]


def _one(db: Session, name: str) -> Product:
    found = resolve_products(db, name)
    if not found:
        raise ToolError(f"I couldn't find a product matching '{name}'.")
    return found[0]


def _store(db: Session) -> Location:
    loc = db.scalar(select(Location).where(Location.type == "store").order_by(Location.id)) or db.scalar(select(Location))
    if not loc:
        raise ToolError("No location is configured yet.")
    return loc


# ------------------------------------------------------------------ handlers

def stock_level(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    products = resolve_products(db, str(args.get("product", "")))
    if not products:
        raise ToolError(f"I couldn't find a product matching '{args.get('product')}'.")
    items = []
    for p in products:
        pos = stock.position(db, p.id)
        status = "out" if pos["on_hand"] <= 0 else ("low" if p.reorder_point is not None and pos["available"] <= p.reorder_point else "ok")
        items.append({"product_id": p.id, "product": p.name, "unit": p.unit, **pos, "reorder_point": p.reorder_point,
                      "status": status})
    return {"items": items}


def expiring_items(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 7)
    rows = db.scalars(select(Batch).where(Batch.qty_on_hand > 0, Batch.expiry_date.is_not(None),
                                          Batch.expiry_date <= today() + timedelta(days=days))
                      .order_by(Batch.expiry_date).limit(25)).unique()
    return {"days": days, "items": [{"product": b.product.name, "batch_no": b.batch_no, "qty": b.qty_on_hand, "unit": b.product.unit,
                                     "expiry_date": b.expiry_date.isoformat() if b.expiry_date else None,
                                     "days_left": (b.expiry_date - today()).days if b.expiry_date else None,
                                     "location": b.location.name, "value": round(b.qty_on_hand * b.cost_price, 2)} for b in rows]}


def pending_approvals(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    prs = list(db.scalars(select(PurchaseRequest).where(PurchaseRequest.status == PR.PENDING)
                          .order_by(PurchaseRequest.created_at)).unique())
    mine = [pr for pr in prs if (c := approvals.current_approval(pr)) and (user.role == Role.ADMIN or c.approver_role == user.role)]
    items = []
    for pr in (mine or prs)[:10]:
        sup = pr.final_supplier or pr.suggested_supplier
        cur = approvals.current_approval(pr)
        items.append({"id": pr.id, "product": pr.product.name, "qty": pr.final_qty or pr.suggested_qty, "unit": pr.product.unit,
                      "supplier": sup.name if sup else None, "est_total": pr.est_total,
                      "level": cur.approver_role if cur else None})
    return {"total_pending": len(prs), "waiting_for_you": len(mine), "items": items}


def best_supplier(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    p = _one(db, str(args.get("product", "")))
    choice = supplier_scoring.rank_for_product(db, p.id)
    if not choice:
        raise ToolError(f"No supplier has a price for {p.name}.")
    return {"product": p.name, "best": {"name": choice.supplier_name, "score": choice.score, "unit_price": choice.unit_price,
                                        "lead_days": choice.lead_days, "breakdown": choice.breakdown},
            "alternatives": choice.alternatives[1:4]}


def low_stock(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    levels = stock.levels(db)
    out = []
    for p in db.scalars(select(Product).where(Product.is_active.is_(True))).unique():
        pos = levels.get(p.id, {"on_hand": 0.0, "on_order": 0.0, "available": 0.0})
        if pos["on_hand"] <= 0 or (p.reorder_point is not None and pos["available"] <= p.reorder_point):
            out.append({"product": p.name, "unit": p.unit, **pos, "reorder_point": p.reorder_point,
                        "status": "out" if pos["on_hand"] <= 0 else "low"})
    out.sort(key=lambda x: (x["status"] != "out", x["available"]))
    return {"count": len(out), "items": out[:15]}


def open_orders(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    stmt = select(PurchaseOrder).where(PurchaseOrder.status.in_(PO.OPEN))
    if user.role == Role.SUPPLIER:
        stmt = stmt.where(PurchaseOrder.supplier_id == user.supplier_id)
    rows = list(db.scalars(stmt.order_by(PurchaseOrder.expected_date)).unique())
    return {"count": len(rows), "items": [{"po_no": po.po_no, "supplier": po.supplier.name, "status": po.status,
                                           "expected": po.expected_date.isoformat() if po.expected_date else None,
                                           "total": po.total, "late": bool(po.predicted_date and today() > po.predicted_date)}
                                          for po in rows[:12]]}


def sales_summary(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    days = int(args.get("days") or 7)
    since = now() - timedelta(days=days)
    total, count = db.execute(select(func.coalesce(func.sum(Sale.total), 0), func.count()).where(Sale.sold_at >= since)).one()
    top = db.execute(select(Product.name, func.sum(SaleLine.line_total)).join(Sale, Sale.id == SaleLine.sale_id)
                     .join(Product, Product.id == SaleLine.product_id).where(Sale.sold_at >= since)
                     .group_by(Product.name).order_by(func.sum(SaleLine.line_total).desc()).limit(5)).all()
    return {"days": days, "revenue": round(float(total), 2), "bills": count,
            "top_products": [{"product": n, "revenue": round(float(v), 2)} for n, v in top]}


def demand_forecast(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    p = _one(db, str(args.get("product", "")))
    fcs = forecast.forecasts_for(db, p.id)
    if not fcs:
        raise ToolError(f"No forecast is available for {p.name} yet — run the Decision agent.")
    return {"product": p.name, "unit": p.unit, "next_7_days": round(sum(f.predicted_qty for f in fcs[:7]), 1),
            "next_30_days": round(sum(f.predicted_qty for f in fcs), 1), "reorder_point": p.reorder_point}


def draft_purchase_request(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    p = _one(db, str(args.get("product", "")))
    try:
        qty = float(args.get("qty") or 0)
    except (TypeError, ValueError):
        raise ToolError("Please give a quantity, e.g. 'create a purchase request for 50 kg sugar'.")
    if qty <= 0:
        raise ToolError("Please give a quantity greater than zero.")
    open_pr = db.scalar(select(PurchaseRequest).where(PurchaseRequest.product_id == p.id, PurchaseRequest.status.in_(PR.OPEN)))
    pr = purchasing.create_request(db, product_id=p.id, location_id=_store(db).id, qty=qty, supplier_id=None, user=user,
                                   created_by="user", reason_text=f"Drafted by {user.name} via the assistant", submit=False)
    db.commit()
    return {"id": pr.id, "status": pr.status, "product": p.name, "qty": qty, "unit": p.unit,
            "supplier": pr.suggested_supplier.name if pr.suggested_supplier else None, "est_total": pr.est_total,
            "note": "Draft only — submit it on the Purchase requests page for normal approval.",
            "existing_open_request": open_pr.id if open_pr else None}


P = {"type": "object", "properties": {"product": {"type": "string", "description": "product name, SKU or barcode"}},
     "required": ["product"]}
DAYS = {"type": "object", "properties": {"days": {"type": "integer", "description": "look-ahead / look-back in days"}}}
NONE: dict[str, Any] = {"type": "object", "properties": {}}

TOOLS: dict[str, ToolSpec] = {
    "stock_level": ToolSpec(Tool("stock_level", "Current on-hand, on-order and available stock for a product (word or fuzzy match).", P),
                            "stock.read", stock_level),
    "expiring_items": ToolSpec(Tool("expiring_items", "Batches expiring within N days (default 7).", DAYS), "stock.read", expiring_items),
    "pending_approvals": ToolSpec(Tool("pending_approvals", "Purchase requests waiting for approval.", NONE), "purchasing.read",
                                  pending_approvals),
    "best_supplier": ToolSpec(Tool("best_supplier", "Best-scoring supplier for a product with score breakdown.", P),
                              "suppliers.read", best_supplier),
    "low_stock": ToolSpec(Tool("low_stock", "Products at or below their reorder point, or out of stock.", NONE), "stock.read", low_stock),
    "open_orders": ToolSpec(Tool("open_orders", "Open purchase orders with expected dates.", NONE), ("po.read", "portal.use"), open_orders),
    "sales_summary": ToolSpec(Tool("sales_summary", "Revenue, bill count and top products over the last N days.", DAYS),
                              "sales.read", sales_summary),
    "demand_forecast": ToolSpec(Tool("demand_forecast", "Forecast demand for a product for the next 7 and 30 days.", P),
                                "products.read", demand_forecast),
    "draft_purchase_request": ToolSpec(Tool("draft_purchase_request",
                                            "Create a DRAFT purchase request (it still needs normal approval).",
                                            {"type": "object", "properties": {"product": {"type": "string"},
                                                                              "qty": {"type": "number"}},
                                             "required": ["product", "qty"]}),
                                       "purchasing.write", draft_purchase_request),
}


def allowed_tools(user: User) -> list[ToolSpec]:
    def ok(perm: str | tuple[str, ...]) -> bool:
        return any(allowed(user.role, p) for p in ((perm,) if isinstance(perm, str) else perm))

    return [t for t in TOOLS.values() if ok(t.permission)]


def call(db: Session, user: User, name: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError(f"Unknown tool {name}")
    if spec not in allowed_tools(user):
        raise ToolError("You don't have permission for that.")
    return spec.handler(db, user, args or {})

