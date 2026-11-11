"""Supplier scoring (spec 7.4).

score = w_price·price_score + w_ontime·on_time_pct + w_lead·lead_score + w_quality·quality_score
price_score = 100 × min_price / supplier_price · lead_score = 100 × min_lead / supplier_lead · quality = 100 − reject %"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import now, start_of_day, today
from app.models.ai import SupplierScore
from app.models.catalog import Supplier, SupplierProduct
from app.models.purchasing import PoLine, PurchaseOrder
from app.services import settings as settings_svc

HISTORY_DAYS = 365
NEUTRAL_ON_TIME = 75.0  # suppliers without delivery history start neutral, not perfect
NEUTRAL_QUALITY = 95.0


@dataclass
class Stats:
    on_time_pct: float
    avg_lead_days: float | None
    reject_pct: float
    orders: int


def weights(db: Session) -> dict[str, float]:
    w = settings_svc.get(db, "supplier_weights")
    return {k: float(w[k]) for k in ("price", "ontime", "lead", "quality")}


def delivery_stats(db: Session, as_of: date | None = None) -> dict[int, Stats]:
    end = as_of or today()
    since = end - timedelta(days=HISTORY_DAYS)
    cond = (PurchaseOrder.order_date >= since, PurchaseOrder.order_date <= end, PurchaseOrder.delivered_at.is_not(None),
            PurchaseOrder.delivered_at < start_of_day(end + timedelta(days=1)))
    pos = db.execute(select(PurchaseOrder.id, PurchaseOrder.supplier_id, PurchaseOrder.order_date,
                            PurchaseOrder.expected_date, PurchaseOrder.delivered_at).where(*cond)).all()
    qual = db.execute(select(PurchaseOrder.supplier_id, PoLine.received_qty, PoLine.damaged_qty)
                      .join(PoLine, PoLine.po_id == PurchaseOrder.id).where(*cond)).all()
    agg: dict[int, dict[str, Any]] = {}
    for _, sid, od, exp, delivered in pos:
        a = agg.setdefault(sid, {"n": 0, "on_time": 0, "lead": 0.0, "rec": 0.0, "dmg": 0.0})
        a["n"] += 1
        d = delivered.date()
        a["on_time"] += 1 if exp is None or d <= exp else 0
        a["lead"] += (d - od).days
    for sid, rec, dmg in qual:
        a = agg.setdefault(sid, {"n": 0, "on_time": 0, "lead": 0.0, "rec": 0.0, "dmg": 0.0})
        a["rec"] += rec or 0
        a["dmg"] += dmg or 0
    out = {}
    for sid, a in agg.items():
        total = a["rec"] + a["dmg"]
        out[sid] = Stats(on_time_pct=100 * a["on_time"] / a["n"] if a["n"] else NEUTRAL_ON_TIME,
                         avg_lead_days=a["lead"] / a["n"] if a["n"] else None,
                         reject_pct=100 * a["dmg"] / total if total else 100 - NEUTRAL_QUALITY, orders=a["n"])
    return out


def compute_scores(db: Session, as_of: date | None = None, persist: bool = True) -> list[SupplierScore]:
    """Nightly supplier-level scores (Celery 02:00). `as_of` recomputes a historical snapshot (seed trend data)."""
    w = weights(db)
    stats = delivery_stats(db, as_of)
    stamp = start_of_day(as_of) + timedelta(hours=2) if as_of else now()
    sps = list(db.scalars(select(SupplierProduct)).unique())
    min_price: dict[int, float] = {}
    for sp in sps:
        min_price[sp.product_id] = min(min_price.get(sp.product_id, sp.unit_price), sp.unit_price)
    leads = {sid: s.avg_lead_days for sid, s in stats.items() if s.avg_lead_days}
    min_lead = min(leads.values()) if leads else None
    rows = []
    for sup in db.scalars(select(Supplier).where(Supplier.is_active.is_(True))):
        mine = [sp for sp in sps if sp.supplier_id == sup.id]
        price = sum(100 * min_price[sp.product_id] / sp.unit_price for sp in mine) / len(mine) if mine else 0.0
        st = stats.get(sup.id) or Stats(NEUTRAL_ON_TIME, None, 100 - NEUTRAL_QUALITY, 0)
        stated = sum(sp.lead_time_days for sp in mine) / len(mine) if mine else None
        lead_days = st.avg_lead_days or stated or 0.0
        lead = 100 * (min_lead or lead_days) / lead_days if lead_days else 100.0
        quality = max(0.0, 100 - st.reject_pct)
        total = w["price"] * price + w["ontime"] * st.on_time_pct + w["lead"] * min(lead, 100) + w["quality"] * quality
        rows.append(SupplierScore(supplier_id=sup.id, computed_at=stamp, price_score=round(price, 2),
                                  on_time_pct=round(st.on_time_pct, 2), avg_lead_days=round(lead_days, 2),
                                  lead_score=round(min(lead, 100), 2), reject_pct=round(st.reject_pct, 2),
                                  quality_score=round(quality, 2), total_score=round(total, 2), orders_considered=st.orders))
    if persist:
        db.add_all(rows)
        db.flush()
    return rows


@dataclass
class Choice:
    supplier_id: int
    supplier_name: str
    unit_price: float
    lead_days: float
    min_order_qty: float
    score: float
    breakdown: dict[str, float]
    alternatives: list[dict[str, Any]]


def rank_for_product(db: Session, product_id: int, stats: dict[int, Stats] | None = None,
                     w: dict[str, float] | None = None, exclude: set[int] | None = None) -> Choice | None:
    """Best supplier for one product: product-level price/lead scores + supplier-level on-time/quality."""
    w = w or weights(db)
    stats = stats if stats is not None else delivery_stats(db)
    offers = [sp for sp in db.scalars(select(SupplierProduct).where(SupplierProduct.product_id == product_id)).unique()
              if sp.supplier.is_active and (not exclude or sp.supplier_id not in exclude)
              and (sp.valid_till is None or sp.valid_till >= today())]
    if not offers:
        return None
    leads = {sp.supplier_id: (stats[sp.supplier_id].avg_lead_days if sp.supplier_id in stats and
                              stats[sp.supplier_id].avg_lead_days else float(sp.lead_time_days)) or 1.0 for sp in offers}
    min_price = min(sp.unit_price for sp in offers)
    min_lead = min(leads.values())
    ranked = []
    for sp in offers:
        st = stats.get(sp.supplier_id) or Stats(NEUTRAL_ON_TIME, None, 100 - NEUTRAL_QUALITY, 0)
        b = {"price": 100 * min_price / sp.unit_price, "on_time": st.on_time_pct,
             "lead": 100 * min_lead / leads[sp.supplier_id], "quality": max(0.0, 100 - st.reject_pct)}
        score = w["price"] * b["price"] + w["ontime"] * b["on_time"] + w["lead"] * b["lead"] + w["quality"] * b["quality"]
        ranked.append((score, sp, b))
    ranked.sort(key=lambda x: x[0], reverse=True)
    score, best, b = ranked[0]
    return Choice(best.supplier_id, best.supplier.name, best.unit_price, round(leads[best.supplier_id], 1),
                  best.min_order_qty, round(score, 1), {k: round(v, 1) for k, v in b.items()},
                  [{"supplier_id": sp.supplier_id, "name": sp.supplier.name, "unit_price": sp.unit_price,
                    "lead_days": round(leads[sp.supplier_id], 1), "score": round(s, 1)} for s, sp, _ in ranked])
