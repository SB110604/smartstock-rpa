"""What-if simulator (spec 9.14): re-run the reorder maths under changed assumptions without saving anything."""

import math
from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import today
from app.ml import forecast, inventory
from app.models.ai import Forecast
from app.models.catalog import Product
from app.services import learning, stock, supplier_scoring
from app.services import settings as settings_svc


def _calc(ctx: tuple[Any, ...], choice: Any, demand_factor: float, lead_add: float, level: float) -> inventory.OrderCalc:
    p, series, sigma, pos, cf, s, review = ctx
    lead = max(1.0, math.ceil((choice.lead_days if choice else 3.0) + lead_add))
    d = [x * demand_factor for x in series]
    return inventory.order_quantity(
        mean_daily_lead=float(np.mean(d[: int(lead)] or d)), mean_daily_year=float(np.mean(d)),
        sigma_daily=sigma * demand_factor, lead_days=lead, review_days=review, service_level=level,
        ordering_cost=float(s["ordering_cost_S"]), holding_pct=float(s["holding_cost_pct"]),
        unit_cost=choice.unit_price if choice else p.cost_price, on_hand=pos["on_hand"], on_order=pos["on_order"],
        pack_size=p.pack_size, min_order_qty=p.min_order_qty, correction_factor=cf,
        perishable_shelf_days=p.shelf_life_days if p.is_perishable else None)


def simulate(db: Session, *, demand_change_pct: float = 0.0, lead_time_change_days: float = 0.0,
             unavailable_supplier_id: int | None = None, service_level: float | None = None,
             category_id: int | None = None, product_ids: list[int] | None = None, horizon_days: int = 30) -> dict[str, Any]:
    s = settings_svc.get_all(db)
    sl = float(service_level if service_level is not None else s["service_level"])
    review = float(s["review_period_days"])
    factor = 1 + demand_change_pct / 100
    stmt = select(Product).where(Product.is_active.is_(True))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if product_ids:
        stmt = stmt.where(Product.id.in_(product_ids))
    products = list(db.scalars(stmt.order_by(Product.name)).unique())
    fc: dict[int, list[float]] = defaultdict(list)
    for f in db.scalars(select(Forecast).where(Forecast.date >= today()).order_by(Forecast.date)):
        fc[f.product_id].append(f.predicted_qty)
    hist = forecast.demand_matrix(db, days=90)
    stats = supplier_scoring.delivery_stats(db)
    w = supplier_scoring.weights(db)
    levels = stock.levels(db)
    rows, totals = [], defaultdict(float)
    for p in products:
        series = fc.get(p.id) or ([float(hist[p.id].tail(28).mean())] * 30 if p.id in hist else [])
        if not series:
            continue
        sigma = float(np.std(hist[p.id].values)) if p.id in hist else 0.0
        pos = levels.get(p.id, {"on_hand": 0.0, "on_order": 0.0})
        cf = learning.correction_factor(db, p.id)
        base_choice = supplier_scoring.rank_for_product(db, p.id, stats, w)
        alt_choice = (supplier_scoring.rank_for_product(db, p.id, stats, w, exclude={unavailable_supplier_id})
                      if unavailable_supplier_id else base_choice)

        ctx = (p, series, sigma, pos, cf, s, review)
        base = _calc(ctx, base_choice, 1.0, 0.0, float(s["service_level"]))
        new = _calc(ctx, alt_choice, factor, lead_time_change_days, sl)
        unit_cost = alt_choice.unit_price if alt_choice else p.cost_price
        demand_h = sum(series[:horizon_days]) * factor
        cover_days = (pos["on_hand"] + pos["on_order"]) / new.mean_daily if new.mean_daily > 0 else float("inf")
        stockout_risk = cover_days < new.lead_days
        cost = {"purchase": round(new.order_qty * unit_cost, 2),
                "holding": round((new.order_qty / 2 + new.safety_stock) * new.holding_cost_per_unit * horizon_days / 365, 2),
                "ordering": round(float(s["ordering_cost_S"]) * (demand_h / new.eoq if new.eoq else 0), 2)}
        no_supplier = unavailable_supplier_id is not None and alt_choice is None
        rows.append({
            "product_id": p.id, "product": p.name, "unit": p.unit,
            "supplier": alt_choice.supplier_name if alt_choice else None,
            "supplier_changed": bool(base_choice and alt_choice and base_choice.supplier_id != alt_choice.supplier_id),
            "no_supplier": no_supplier,
            "current": {"rop": round(base.reorder_point, 1), "ss": round(base.safety_stock, 1), "eoq": round(base.eoq, 1),
                        "order_qty": base.order_qty},
            "new": {"rop": round(new.reorder_point, 1), "ss": round(new.safety_stock, 1), "eoq": round(new.eoq, 1),
                    "order_qty": new.order_qty, "lead_days": new.lead_days},
            "cover_days": None if math.isinf(cover_days) else round(cover_days, 1), "stockout_risk": stockout_risk or no_supplier,
            "cost": cost,
        })
        totals["order_value"] += cost["purchase"]
        totals["holding_cost"] += cost["holding"]
        totals["ordering_cost"] += cost["ordering"]
        totals["stockout_risk"] += 1 if (stockout_risk or no_supplier) else 0
        totals["reorder_now"] += 1 if new.should_order else 0
        totals["ss_change"] += new.safety_stock - base.safety_stock
    return {"assumptions": {"demand_change_pct": demand_change_pct, "lead_time_change_days": lead_time_change_days,
                            "unavailable_supplier_id": unavailable_supplier_id, "service_level": sl, "horizon_days": horizon_days},
            "totals": {k: round(v, 2) for k, v in totals.items()}, "products": rows}
