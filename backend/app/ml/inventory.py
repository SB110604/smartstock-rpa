"""Reorder mathematics (spec 7.3). Pure functions — no database access — so they are easy to test and explain."""

import math
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Any


def z_value(service_level: float) -> float:
    """Standard-normal quantile for the cycle service level (0.95 → 1.645)."""
    service_level = min(max(service_level, 0.5), 0.9999)
    return NormalDist().inv_cdf(service_level)


def safety_stock(z: float, sigma_d: float, lead_days: float) -> float:
    """SS = z × σ_d × √L"""
    return max(0.0, z * max(sigma_d, 0.0) * math.sqrt(max(lead_days, 0.0)))


def reorder_point(mean_daily: float, lead_days: float, ss: float) -> float:
    """ROP = d̄ × L + SS"""
    return max(0.0, mean_daily * lead_days + ss)


def eoq(annual_demand: float, ordering_cost: float, holding_cost_per_unit: float) -> float:
    """EOQ = √(2DS / H). Zero demand or zero holding cost → 0 (nothing sensible to order)."""
    if annual_demand <= 0 or holding_cost_per_unit <= 0 or ordering_cost <= 0:
        return 0.0
    return math.sqrt(2 * annual_demand * ordering_cost / holding_cost_per_unit)


def round_to_pack(qty: float, pack_size: float, min_order_qty: float) -> float:
    pack = pack_size if pack_size and pack_size > 0 else 1.0
    q = math.ceil(round(qty / pack, 6)) * pack if qty > 0 else 0.0
    return float(max(q, min_order_qty or 0.0))


@dataclass
class OrderCalc:
    lead_days: float
    review_days: float
    mean_daily: float
    sigma_daily: float
    service_level: float
    z: float
    safety_stock: float
    reorder_point: float
    annual_demand: float
    ordering_cost: float
    holding_cost_per_unit: float
    eoq: float
    on_hand: float
    on_order: float
    need: float
    correction_factor: float
    perishable_cap: float | None
    raw_qty: float
    order_qty: float
    pack_size: float
    min_order_qty: float
    should_order: bool

    def as_dict(self) -> dict[str, Any]:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def order_quantity(
    *,
    mean_daily_lead: float,
    mean_daily_year: float,
    sigma_daily: float,
    lead_days: float,
    review_days: float,
    service_level: float,
    ordering_cost: float,
    holding_pct: float,
    unit_cost: float,
    on_hand: float,
    on_order: float,
    pack_size: float,
    min_order_qty: float,
    correction_factor: float = 1.0,
    perishable_shelf_days: int | None = None,
) -> OrderCalc:
    """Full spec 7.3 recommendation.

    qty = max(EOQ, ROP + d̄ × review − (on_hand + on_order)) × correction,
    capped at d̄ × shelf_life × 0.8 for perishables, then rounded up to the pack size and at least the MOQ.
    An order is suggested when on_hand + on_order ≤ ROP."""
    z = z_value(service_level)
    ss = safety_stock(z, sigma_daily, lead_days)
    rop = reorder_point(mean_daily_lead, lead_days, ss)
    annual = mean_daily_year * 365
    h = holding_pct / 100 * unit_cost
    q_eoq = eoq(annual, ordering_cost, h)
    position = on_hand + on_order
    need = rop + mean_daily_lead * review_days - position
    raw = max(q_eoq, need) * correction_factor
    cap = mean_daily_lead * perishable_shelf_days * 0.8 if perishable_shelf_days else None
    capped = min(raw, cap) if cap is not None else raw
    should = position <= rop and mean_daily_lead > 0
    qty = round_to_pack(capped, pack_size, min_order_qty) if should and capped > 0 else 0.0
    return OrderCalc(
        lead_days=lead_days, review_days=review_days, mean_daily=mean_daily_lead, sigma_daily=sigma_daily,
        service_level=service_level, z=z, safety_stock=ss, reorder_point=rop, annual_demand=annual,
        ordering_cost=ordering_cost, holding_cost_per_unit=h, eoq=q_eoq, on_hand=on_hand, on_order=on_order,
        need=need, correction_factor=correction_factor, perishable_cap=cap, raw_qty=raw, order_qty=qty,
        pack_size=pack_size, min_order_qty=min_order_qty, should_order=should,
    )


def reason_text(c: OrderCalc, unit: str, forecast_window_total: float) -> str:
    """Template sentence (spec 7.3 example). The LLM may polish it; this is the fallback."""
    window = int(c.lead_days + c.review_days)
    parts = [
        f"Forecast {forecast_window_total:.0f} {unit} over next {window} days (lead {c.lead_days:g} + review {c.review_days:g}).",
        f"On hand {c.on_hand:g}, on order {c.on_order:g}, safety stock {c.safety_stock:.0f}.",
    ]
    detail = f"EOQ {c.eoq:.0f}"
    if c.pack_size and c.pack_size > 1:
        detail += f", rounded to pack of {c.pack_size:g}"
    if abs(c.correction_factor - 1) >= 0.005:
        detail += f", ×{c.correction_factor:.2f} learned correction"
    if c.perishable_cap is not None and c.raw_qty > c.perishable_cap:
        detail += f", capped at {c.perishable_cap:.0f} for shelf life"
    parts.append(f"Suggest {c.order_qty:g} ({detail}).")
    return " ".join(parts)
