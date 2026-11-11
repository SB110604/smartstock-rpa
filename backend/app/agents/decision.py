"""Decision agent (spec 7.3): forecast → safety stock, reorder point, EOQ → order recommendation with full reasoning."""

import math
from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentResult
from app.ml import forecast, inventory
from app.models.ai import Forecast
from app.models.catalog import Product
from app.models.core import Location
from app.services import learning, stock, supplier_scoring


class DecisionAgent(Agent):
    name = "decision"
    title = "Decision (forecast + ROP + EOQ)"
    description = "Forecasts demand, recomputes safety stock / reorder point / EOQ and recommends order quantities."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        s = ctx.settings
        reg, art = forecast.ensure_model(db)
        n_fc = forecast.write_forecasts(db, reg, art)
        fc: dict[int, list[float]] = defaultdict(list)
        for f in db.scalars(select(Forecast).where(Forecast.date >= ctx.day).order_by(Forecast.date)):
            fc[f.product_id].append(f.predicted_qty)
        hist = forecast.demand_matrix(db, days=90)
        sigma = {int(p): float(np.std(hist[p].values)) for p in hist.columns}
        stats = supplier_scoring.delivery_stats(db)
        weights = supplier_scoring.weights(db)
        stores = list(db.scalars(select(Location).where(Location.type == "store", Location.is_active.is_(True))))
        products = list(db.scalars(select(Product).where(Product.is_active.is_(True))).unique())
        recs: list[dict[str, Any]] = []
        review = float(s["review_period_days"])
        for loc in stores:
            levels = stock.levels(db, loc.id)
            for p in products:
                series = fc.get(p.id, [])
                if not series:
                    continue
                choice = supplier_scoring.rank_for_product(db, p.id, stats, weights)
                lead = float(max(1, math.ceil(choice.lead_days))) if choice else 3.0
                unit_cost = choice.unit_price if choice else p.cost_price
                window = series[: int(lead)] or series
                mean_lead = float(np.mean(window))
                mean_year = float(np.mean(series))
                pos = levels.get(p.id, {"on_hand": 0.0, "on_order": 0.0})
                cf = learning.correction_factor(db, p.id)
                calc = inventory.order_quantity(
                    mean_daily_lead=mean_lead, mean_daily_year=mean_year, sigma_daily=sigma.get(p.id, 0.0),
                    lead_days=lead, review_days=review, service_level=float(s["service_level"]),
                    ordering_cost=float(s["ordering_cost_S"]), holding_pct=float(s["holding_cost_pct"]), unit_cost=unit_cost,
                    on_hand=pos["on_hand"], on_order=pos["on_order"], pack_size=p.pack_size,
                    min_order_qty=max(p.min_order_qty, choice.min_order_qty if choice else 0),
                    correction_factor=cf, perishable_shelf_days=p.shelf_life_days if p.is_perishable else None,
                )
                horizon_total = float(sum(series[: int(lead + review)]))
                text = inventory.reason_text(calc, p.unit, horizon_total)
                p.reorder_point = round(calc.reorder_point, 2)
                p.safety_stock = round(calc.safety_stock, 2)
                p.eoq = round(calc.eoq, 2)
                p.calc_json = {
                    "forecast_daily_lead": round(mean_lead, 2), "forecast_daily_30d": round(mean_year, 2),
                    "sigma_daily": round(sigma.get(p.id, 0.0), 2), "lead_time_days": lead, "review_period_days": review,
                    "service_level": s["service_level"], "z": round(calc.z, 3), "safety_stock": round(calc.safety_stock, 2),
                    "reorder_point": round(calc.reorder_point, 2), "annual_demand": round(calc.annual_demand, 1),
                    "ordering_cost_S": s["ordering_cost_S"], "holding_cost_H": round(calc.holding_cost_per_unit, 2),
                    "eoq": round(calc.eoq, 2), "correction_factor": cf, "supplier": choice.supplier_name if choice else None,
                    "model": art["choice"].get(p.id, "ma28"), "model_version": reg.version,
                    "explanation": (f"SS = z({calc.z:.2f}) × σ({calc.sigma_daily:.2f}) × √{lead:g} = {calc.safety_stock:.1f}; "
                                    f"ROP = {mean_lead:.2f} × {lead:g} + SS = {calc.reorder_point:.1f}; "
                                    f"EOQ = √(2 × {calc.annual_demand:.0f} × {s['ordering_cost_S']} / {calc.holding_cost_per_unit:.2f}) "
                                    f"= {calc.eoq:.1f}."),
                }
                if calc.should_order and calc.order_qty > 0 and not p.reorder_paused:
                    recs.append({
                        "product_id": p.id, "location_id": loc.id, "qty": calc.order_qty, "reason_text": text,
                        "priority": p.priority, "out_of_stock": pos["on_hand"] <= 0,
                        "supplier_id": choice.supplier_id if choice else None,
                        "reason_json": {**calc.as_dict(), "forecast_window_total": round(horizon_total, 1),
                                        "forecast_model": art["choice"].get(p.id, "ma28"), "model_version": reg.version},
                    })
        db.flush()
        return AgentResult(items_processed=len(products) * max(1, len(stores)),
                           summary={"forecast_rows": n_fc, "model_version": reg.version, "recommendations": len(recs),
                                    "model_mape": reg.metrics.get("mape")},
                           data={"recommendations": recs})
