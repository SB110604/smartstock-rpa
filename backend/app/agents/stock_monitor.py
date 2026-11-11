"""Stock Monitor agent (spec 7.1): positions, low/out-of-stock alerts, dead stock, ABC/XYZ classification."""

from datetime import timedelta

from sqlalchemy import select, text

from app.agents.base import Agent, AgentContext, AgentResult
from app.core.timeutil import now
from app.ml import classify
from app.models.catalog import Product
from app.models.core import Location
from app.services import alerts, stock


class StockMonitorAgent(Agent):
    name = "stock_monitor"
    title = "Stock Monitor"
    description = "On-hand, on-order and available per product; low-stock, out-of-stock and dead-stock alerts; ABC/XYZ."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        products = list(db.scalars(select(Product).where(Product.is_active.is_(True))).unique())
        stores = list(db.scalars(select(Location).where(Location.type == "store", Location.is_active.is_(True))))
        dead_days = int(ctx.settings["dead_stock_days"])
        last_sale = dict(db.execute(text(
            "SELECT l.product_id, MAX(s.sold_at) FROM sale_lines l JOIN sales s ON s.id = l.sale_id GROUP BY 1")).all())
        positions: dict[int, dict[int, dict[str, float]]] = {}
        low, out, dead, recovered = [], [], [], 0
        for loc in stores:
            lv = stock.levels(db, loc.id)
            positions[loc.id] = {}
            for p in products:
                pos = lv.get(p.id, {"on_hand": 0.0, "on_order": 0.0, "available": 0.0})
                positions[loc.id][p.id] = pos
                key_low, key_out = f"low_stock:{p.id}:{loc.id}", f"out_of_stock:{p.id}:{loc.id}"
                sold_recently = last_sale.get(p.id) and last_sale[p.id] >= now() - timedelta(days=dead_days)
                if pos["on_hand"] <= 0 and sold_recently:
                    out.append(p.id)
                    alerts.raise_alert(db, "out_of_stock", f"{p.name} is out of stock at {loc.name}"
                                       + (f" ({pos['on_order']:g} on order)." if pos["on_order"] else " and nothing is on order."),
                                       severity="critical" if not pos["on_order"] else "warning", product_id=p.id,
                                       ref_type="location", ref_id=loc.id, key=key_out,
                                       data={**pos, "reorder_point": p.reorder_point})
                    alerts.resolve_by_key(db, key_low, "now out of stock")
                elif p.reorder_point is not None and pos["available"] <= p.reorder_point and sold_recently:
                    low.append(p.id)
                    alerts.raise_alert(db, "low_stock", f"{p.name} at {loc.name}: available {pos['available']:g} "
                                       f"(on hand {pos['on_hand']:g} + on order {pos['on_order']:g}) is at or below the reorder "
                                       f"point {p.reorder_point:g}.", product_id=p.id, ref_type="location", ref_id=loc.id,
                                       key=key_low, data={**pos, "reorder_point": p.reorder_point})
                    recovered += alerts.resolve_by_key(db, key_out, "restocked")
                else:
                    recovered += alerts.resolve_by_key(db, key_low, "recovered") + alerts.resolve_by_key(db, key_out, "restocked")
                last = last_sale.get(p.id)
                if pos["on_hand"] > 0 and (last is None or last < now() - timedelta(days=dead_days)):
                    days = (now() - last).days if last else None
                    value = round(pos["on_hand"] * p.cost_price, 2)
                    dead.append(p.id)
                    alerts.raise_alert(
                        db, "dead_stock",
                        f"{p.name}: {pos['on_hand']:g} {p.unit} (₹{value:,.0f}) with no sales for "
                        f"{days if days is not None else 'over ' + str(dead_days)} days at {loc.name}.",
                        severity="info", product_id=p.id, ref_type="location", ref_id=loc.id, key=f"dead_stock:{p.id}:{loc.id}",
                        data={"days_without_sale": days, "value": value, "suggestions": [
                            "Run a clearance discount (20–30%)", "Bundle with a fast mover", "Stop reordering this item"]})
        classified = 0
        if ctx.triggered_by in ("weekly", "seed", "manual") or any(p.abc_class is None for p in products):
            classes = classify.compute(db)
            for p in products:
                a, x = classes.get(p.id, ("C", "Z"))
                p.abc_class, p.xyz_class = a, x
                classified += 1
        db.flush()
        return AgentResult(
            items_processed=len(products) * max(1, len(stores)),
            summary={"products": len(products), "locations": len(stores), "low_stock": len(low), "out_of_stock": len(out),
                     "dead_stock": len(dead), "recovered": recovered, "classified": classified},
            data={"positions": positions, "low": low, "out": out, "dead": dead},
        )
