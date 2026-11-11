"""SmartStock evaluation (spec section 12): `make eval` → reports/evaluation.md + PNG charts.

Back-tests the last 90 days of the seeded store data:
1. Forecast accuracy — global HistGradientBoosting model vs 28-day moving average, 7-day-ahead forecasts from a weekly
   rolling origin (the model is trained only on data before the test window).
2. Inventory policy simulation on the real daily demand of every product:
   - Baseline: reorder level = 7 days of average sales, order qty = 14 days of average sales, cheapest supplier,
     no FEFO enforcement (shoppers take the freshest stock first), no markdowns.
   - SmartStock: forecast + safety stock + ROP + EOQ (spec 7.3) with perishable cap, best-scored supplier (spec 7.4),
     FEFO picking and expiry markdowns (spec 7.2).
   Both policies start with the same stock and draw lead times from each supplier's real delivery history.
Run from the backend folder: `python scripts/evaluate.py`."""

import math
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter
from sqlalchemy import select

from app.db.session import SessionLocal
from app.ml import forecast, inventory
from app.models import Product, PurchaseOrder, SupplierProduct
from app.services import settings as settings_svc

TEST_DAYS = 90
SEED = 7
MARKDOWN_LIFT = 0.6  # a 30 % markdown on a near-expiry batch lifts that product's demand by ~60 %
MANUAL_MIN_PER_PO, AUTO_MIN_PER_PO = 15, 2
BLUE, ORANGE, AQUA, YELLOW, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#898781"

ROOT = Path(__file__).resolve().parents[1]
OUT = (ROOT.parent / "reports") if (ROOT.parent / "reports").is_dir() else (ROOT / "reports")


# ------------------------------------------------------------------ data

@dataclass
class Offer:
    supplier_id: int
    price: float
    lead: int
    moq: float


@dataclass
class Item:
    id: int
    name: str
    category: str | None
    cost: float
    price: float
    pack: float
    moq: float
    shelf: int | None
    perishable: bool
    offers: list[Offer] = field(default_factory=list)


def load(db: Any) -> tuple[pd.DataFrame, list[Item], dict[int, list[int]], dict[int, float]]:
    y = forecast.demand_matrix(db)
    items = {}
    for p in db.scalars(select(Product).where(Product.is_active.is_(True))).unique():
        items[p.id] = Item(p.id, p.name, p.category.name if p.category else None, p.cost_price, p.selling_price, p.pack_size,
                           p.min_order_qty, p.shelf_life_days, p.is_perishable)
    for sp in db.scalars(select(SupplierProduct)).unique():
        if sp.product_id in items:
            items[sp.product_id].offers.append(Offer(sp.supplier_id, sp.unit_price, sp.lead_time_days, sp.min_order_qty))
    start = y.index[-TEST_DAYS].date()
    # each supplier's real delay distribution (actual − promised days) from deliveries before the test window
    delays: dict[int, list[int]] = defaultdict(list)
    on_time: dict[int, list[int]] = defaultdict(list)
    for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.delivered_at.is_not(None), PurchaseOrder.order_date < start)):
        if po.expected_date:
            d = (po.delivered_at.date() - po.expected_date).days
            delays[po.supplier_id].append(d)
            on_time[po.supplier_id].append(1 if d <= 0 else 0)
    reliability = {s: float(np.mean(v)) for s, v in on_time.items()}
    return y, [i for i in items.values() if i.offers and i.id in y.columns], delays, reliability


# ------------------------------------------------------------------ 1. forecast accuracy

def forecast_backtest(db: Any, y: pd.DataFrame) -> dict[str, Any]:
    fests, cats = forecast.festival_dates(db), forecast._categories(db)
    cut = len(y) - TEST_DAYS
    model = forecast._fit(y.iloc[:cut], fests, cats)
    rows = []
    for origin in range(cut, len(y) - 6, 7):
        hist = y.iloc[:origin]
        pred = forecast.recursive_forecast(model, hist, 7, fests, cats)
        ma = hist.tail(28).mean()
        actual = y.iloc[origin:origin + 7]
        for p in y.columns:
            a = actual[p].values
            rows.append({"week": actual.index[0].date(), "product": p, "actual": a, "model": pred[p].values,
                         "ma": np.full(7, ma[p])})
    m_mape = [forecast.mape(r["actual"], r["model"]) for r in rows]
    b_mape = [forecast.mape(r["actual"], r["ma"]) for r in rows]
    all_a = np.concatenate([r["actual"] for r in rows])
    all_m = np.concatenate([r["model"] for r in rows])
    all_b = np.concatenate([r["ma"] for r in rows])
    weekly = defaultdict(lambda: {"m": [], "b": []})
    for r, mm, bb in zip(rows, m_mape, b_mape, strict=True):
        if mm is not None:
            weekly[r["week"]]["m"].append(mm)
        if bb is not None:
            weekly[r["week"]]["b"].append(bb)
    return {
        "mape_model": float(np.mean([m for m in m_mape if m is not None])),
        "mape_ma": float(np.mean([b for b in b_mape if b is not None])),
        "rmse_model": forecast.rmse(all_a, all_m), "rmse_ma": forecast.rmse(all_a, all_b),
        "wape_model": float(np.abs(all_a - all_m).sum() / all_a.sum() * 100),
        "wape_ma": float(np.abs(all_a - all_b).sum() / all_a.sum() * 100),
        "weekly": [(w, float(np.mean(v["m"])), float(np.mean(v["b"]))) for w, v in sorted(weekly.items())],
        "origins": len(weekly), "model": model,
    }


# ------------------------------------------------------------------ 2. policy simulation

@dataclass
class Batch:
    qty: float
    expiry: int | None  # day index
    cost: float


@dataclass
class Result:
    stockout_days: int = 0
    demand: float = 0.0
    sold: float = 0.0
    wasted_value: float = 0.0
    inventory_value: list[float] = field(default_factory=list)
    orders: int = 0
    purchase_cost: float = 0.0
    deliveries: int = 0
    on_time: int = 0
    markdown_cost: float = 0.0
    revenue: float = 0.0


def simulate(item: Item, demand: np.ndarray, hist: np.ndarray, policy: str, rng: np.random.Generator,
             delays: dict[int, list[int]], reliability: dict[int, float], fc: np.ndarray | None,
             s: dict[str, Any]) -> tuple[Result, list[float]]:
    res = Result()
    avg = max(float(hist[-90:].mean()), 0.01)
    sigma = float(hist[-90:].std())
    if policy == "baseline":
        offer = min(item.offers, key=lambda o: o.price)
    else:
        min_p, min_l = min(o.price for o in item.offers), min(o.lead for o in item.offers)
        def score(o: Offer) -> float:
            w = s["supplier_weights"]
            return (w["price"] * 100 * min_p / o.price + w["ontime"] * 100 * reliability.get(o.supplier_id, 0.75)
                    + w["lead"] * 100 * min_l / o.lead + w["quality"] * 95)
        offer = max(item.offers, key=score)
    shelf = item.shelf
    batches: list[Batch] = [Batch(round(avg * 14), (shelf // 2) if shelf else None, offer.price)]
    pipeline: list[tuple[int, float, bool]] = []  # (arrival day, qty, on_time)
    trajectory = []
    crit = int(s["expiry_thresholds"]["critical"])
    for t, base_d in enumerate(demand):
        # arrivals
        for arr in [x for x in pipeline if x[0] == t]:
            batches.append(Batch(arr[1], t + shelf if shelf else None, offer.price))
            res.deliveries += 1
            res.on_time += int(arr[2])
            pipeline.remove(arr)
        # expiry: expired stock is written off
        for b in batches:
            if b.expiry is not None and b.expiry <= t and b.qty > 0:
                res.wasted_value += b.qty * b.cost
                b.qty = 0
        batches = [b for b in batches if b.qty > 1e-9]
        d = float(base_d)
        # SmartStock: critical batches that will not sell in time get a 30 % markdown (lifts demand)
        if policy == "smart" and shelf:
            for b in batches:
                if b.expiry is not None and 0 < b.expiry - t <= crit and b.qty > avg * (b.expiry - t):
                    extra = min(b.qty, avg * MARKDOWN_LIFT)
                    d += extra
                    res.markdown_cost += extra * item.price * 0.30
                    break
        res.demand += float(base_d)
        # picking: FEFO (smart) vs freshest-first (baseline)
        order = sorted(batches, key=lambda b: b.expiry if b.expiry is not None else 10**9)
        if policy == "baseline":
            order = order[::-1]
        need = d
        for b in order:
            take = min(b.qty, need)
            b.qty -= take
            need -= take
            if need <= 1e-9:
                break
        sold = d - need
        res.sold += min(sold, float(base_d)) if need > 1e-9 else float(base_d)
        res.revenue += sold * item.price
        on_hand = sum(b.qty for b in batches)
        if need > 1e-9 and base_d > 0:
            res.stockout_days += 1
        res.inventory_value.append(on_hand * item.cost)
        trajectory.append(on_hand)
        on_order = sum(x[1] for x in pipeline)
        position = on_hand + on_order
        # ordering decision at end of day
        if policy == "baseline":
            rop, qty = 7 * avg, math.ceil(14 * avg / item.pack) * item.pack
            place = position <= rop
        else:
            window = fc[t + 1: t + 31] if fc is not None and t + 1 < len(fc) else np.array([avg])
            lead = max(1, offer.lead + 1)
            calc = inventory.order_quantity(
                mean_daily_lead=float(np.mean(window[:lead])), mean_daily_year=float(np.mean(window)), sigma_daily=sigma,
                lead_days=lead, review_days=float(s["review_period_days"]), service_level=float(s["service_level"]),
                ordering_cost=float(s["ordering_cost_S"]), holding_pct=float(s["holding_cost_pct"]), unit_cost=offer.price,
                on_hand=on_hand, on_order=on_order, pack_size=item.pack, min_order_qty=max(item.moq, offer.moq),
                perishable_shelf_days=shelf if item.perishable else None)
            place, qty = calc.should_order, calc.order_qty
        if place and qty > 0 and not pipeline:
            delay = int(rng.choice(delays[offer.supplier_id])) if delays.get(offer.supplier_id) else 0
            pipeline.append((t + 1 + max(1, offer.lead + delay), qty, delay <= 0))
            res.orders += 1
            res.purchase_cost += qty * offer.price
    return res, trajectory


def smart_forecasts(db: Any, y: pd.DataFrame, model: Any) -> dict[int, np.ndarray]:
    """Weekly re-forecast (like the daily agent) stitched into one 30-day-ahead series per product and day."""
    fests, cats = forecast.festival_dates(db), forecast._categories(db)
    cut = len(y) - TEST_DAYS
    out = {int(p): np.zeros(TEST_DAYS + 31) for p in y.columns}
    for origin in range(cut, len(y), 7):
        pred = forecast.recursive_forecast(model, y.iloc[:origin], 37, fests, cats)
        for p in y.columns:
            seg = pred[p].values
            i = origin - cut
            out[int(p)][i:i + 37] = seg[: len(out[int(p)][i:i + 37])]
    return out


# ------------------------------------------------------------------ report

def bar(ax: Any, labels: list[str], a: float, b: float, title: str, fmt: str) -> None:
    ax.bar(labels, [a, b], color=[GREY, BLUE], width=0.55)
    for i, v in enumerate([a, b]):
        ax.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=9)
    ax.set_title(title, fontsize=10)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 10 else f"{v:g}"))
    ax.spines[["top", "right"]].set_visible(False)


def main() -> int:
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    with SessionLocal() as db:
        s = settings_svc.get_all(db)
        y, items, delays, reliability = load(db)
        if len(y) < TEST_DAYS + 120:
            print("Not enough history — run `make seed` first.")
            return 1
        print(f"Backtest window: {y.index[-TEST_DAYS].date()} to {y.index[-1].date()} ({len(items)} products)")
        fa = forecast_backtest(db, y)
        print(f"  forecast: model MAPE {fa['mape_model']:.1f}% vs MA {fa['mape_ma']:.1f}%")
        fcs = smart_forecasts(db, y, fa["model"])
    cut = len(y) - TEST_DAYS
    totals = {"baseline": Result(), "smart": Result()}
    daily_value = {"baseline": np.zeros(TEST_DAYS), "smart": np.zeros(TEST_DAYS)}
    example = max(items, key=lambda i: (i.perishable, float(y[i.id].iloc[cut:].sum())))
    traj: dict[str, list[float]] = {}
    for item in items:
        demand = y[item.id].iloc[cut:].values
        hist = y[item.id].iloc[:cut].values
        for pol in ("baseline", "smart"):
            r, tr = simulate(item, demand, hist, pol, np.random.default_rng(SEED + item.id), delays, reliability,
                             fcs.get(item.id), s)
            tot = totals[pol]
            for k in ("stockout_days", "demand", "sold", "wasted_value", "orders", "purchase_cost", "deliveries", "on_time",
                      "markdown_cost", "revenue"):
                setattr(tot, k, getattr(tot, k) + getattr(r, k))
            daily_value[pol] += np.array(r.inventory_value)
            if item.id == example.id:
                traj[pol] = tr
    del rng
    b, m = totals["baseline"], totals["smart"]
    metric = {
        "Stock-out days (product-days)": (b.stockout_days, m.stockout_days, "{:,.0f}", False),
        "Fill rate": (100 * b.sold / b.demand, 100 * m.sold / m.demand, "{:.1f}%", True),
        "Expired / wasted stock value": (b.wasted_value, m.wasted_value, "₹{:,.0f}", False),
        "Markdown cost (price given away)": (b.markdown_cost, m.markdown_cost, "₹{:,.0f}", False),
        "Average inventory value": (float(daily_value["baseline"].mean()), float(daily_value["smart"].mean()), "₹{:,.0f}", False),
        "Number of purchase orders": (b.orders, m.orders, "{:,.0f}", False),
        "Total purchase cost": (b.purchase_cost, m.purchase_cost, "₹{:,.0f}", False),
        "Purchase cost per unit sold": (b.purchase_cost / max(1, b.sold), m.purchase_cost / max(1, m.sold), "₹{:,.2f}", False),
        "On-time delivery": (100 * b.on_time / max(1, b.deliveries), 100 * m.on_time / max(1, m.deliveries), "{:.1f}%", True),
    }
    saved_min = m.orders * (MANUAL_MIN_PER_PO - AUTO_MIN_PER_PO)

    # charts
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6))
    bar(axes[0], ["28-day MA", "SmartStock model"], fa["mape_ma"], fa["mape_model"], "Forecast MAPE (lower is better)", "{:.1f}%")
    bar(axes[1], ["28-day MA", "SmartStock model"], fa["rmse_ma"], fa["rmse_model"], "Forecast RMSE (units/day)", "{:.2f}")
    weeks = [w for w, _, _ in fa["weekly"]]
    axes[2].plot(weeks, [x for _, _, x in fa["weekly"]], color=GREY, lw=2, label="28-day MA")
    axes[2].plot(weeks, [x for _, x, _ in fa["weekly"]], color=BLUE, lw=2, label="SmartStock model")
    axes[2].set_title("Weekly MAPE over the test window", fontsize=10)
    axes[2].legend(fontsize=8, frameon=False)
    axes[2].tick_params(axis="x", labelrotation=45, labelsize=7)
    axes[2].spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "eval_forecast.png", dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 4, figsize=(14, 3.4))
    labels = ["Baseline", "SmartStock"]
    bar(axes[0], labels, b.stockout_days, m.stockout_days, "Stock-out product-days", "{:,.0f}")
    bar(axes[1], labels, b.wasted_value, m.wasted_value, "Expired stock value (₹)", "{:,.0f}")
    bar(axes[2], labels, metric["Average inventory value"][0], metric["Average inventory value"][1], "Average inventory value (₹)", "{:,.0f}")
    bar(axes[3], labels, metric["Fill rate"][0], metric["Fill rate"][1], "Fill rate (%)", "{:.1f}")
    fig.tight_layout()
    fig.savefig(OUT / "eval_policy.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 3.4))
    days = [y.index[cut + i].date() for i in range(TEST_DAYS)]
    ax.plot(days, traj.get("baseline", []), color=GREY, lw=2, label="Baseline")
    ax.plot(days, traj.get("smart", []), color=BLUE, lw=2, label="SmartStock")
    ax.set_title(f"On-hand stock — {example.name}", fontsize=10)
    ax.legend(fontsize=8, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "eval_example.png", dpi=140)
    plt.close(fig)

    def change(a: float, bb: float, higher_better: bool) -> str:
        if a == 0:
            return "—"
        pct = (bb - a) / abs(a) * 100
        good = pct > 0 if higher_better else pct < 0
        return f"{pct:+.1f}% {'✔' if good else ''}".strip()

    lines = [
        "# SmartStock RPA — Evaluation",
        "",
        f"Generated by `make eval` on {date.today():%d-%m-%Y} from the seeded demo data (Shree Ganesh SuperMart).",
        f"Test window: **{y.index[cut].date():%d-%m-%Y} to {y.index[-1].date():%d-%m-%Y}** ({TEST_DAYS} days, {len(items)} products). "
        "All models were trained only on data before the window.",
        "",
        "## 1. Forecast accuracy",
        "",
        f"Seven-day-ahead forecasts from a weekly rolling origin ({fa['origins']} origins × {len(y.columns)} products).",
        "",
        "| Metric | 28-day moving average | SmartStock model (HistGradientBoosting) | Change |",
        "|---|---:|---:|---:|",
        f"| MAPE | {fa['mape_ma']:.1f}% | {fa['mape_model']:.1f}% | {change(fa['mape_ma'], fa['mape_model'], False)} |",
        f"| RMSE (units/day) | {fa['rmse_ma']:.2f} | {fa['rmse_model']:.2f} | {change(fa['rmse_ma'], fa['rmse_model'], False)} |",
        f"| WAPE | {fa['wape_ma']:.1f}% | {fa['wape_model']:.1f}% | {change(fa['wape_ma'], fa['wape_model'], False)} |",
        "",
        "![Forecast accuracy](eval_forecast.png)",
        "",
        "MAPE is averaged over products and ignores days with zero sales (undefined); WAPE weights errors by volume.",
        "",
        "## 2. Inventory policy simulation",
        "",
        "| Metric | Baseline policy | SmartStock policy | Change |",
        "|---|---:|---:|---:|",
    ]
    for name, (a, bb, fmt, hb) in metric.items():
        lines.append(f"| {name} | {fmt.format(a)} | {fmt.format(bb)} | {change(a, bb, hb)} |")
    lines += [
        f"| Manual purchasing time | {b.orders * MANUAL_MIN_PER_PO / 60:,.1f} h (15 min × PO) | "
        f"{m.orders * AUTO_MIN_PER_PO / 60:,.1f} h (2 min × PO, approval only) | {saved_min / 60:,.1f} h saved |",
        "",
        "![Policy comparison](eval_policy.png)",
        "",
        "![Example product](eval_example.png)",
        "",
        "## 3. Reading the results",
        "",
        "- SmartStock trades **more stock on the shelf** for **far fewer stock-outs and much less expiry waste**: the "
        "spec's EOQ with an ordering cost of ₹500 per order favours fewer, larger orders for cheap fast movers, which "
        "raises average inventory value. Lowering `ordering_cost_S` in Settings (or raising `holding_cost_pct`) shrinks "
        "order sizes; the What-if simulator shows the effect before changing anything.",
        "- Purchase cost is higher partly because SmartStock sells more (higher fill rate) and ends the window holding more "
        "stock; compare *purchase cost per unit sold*.",
        "- Waste falls mainly because of FEFO picking, the shelf-life cap on perishable orders and markdowns on near-expiry "
        "batches.",
        "",
        "## 4. Method and assumptions",
        "",
        "- **Baseline policy**: reorder level = 7 days of average sales, order quantity = 14 days of average sales "
        "(averages from the 90 days before the window), cheapest supplier, no FEFO (shoppers take the freshest batch), "
        "no markdowns.",
        "- **SmartStock policy**: the 7-agent logic — weekly re-forecast, safety stock z·σ·√L, reorder point d̄·L + SS, "
        "EOQ √(2DS/H), order quantity max(EOQ, ROP + d̄·review − position) with the perishable cap and pack rounding, "
        "best-scored supplier (price/on-time/lead/quality weights from settings), FEFO picking, and a 30 % markdown on "
        f"critical-expiry batches that would not sell in time (assumed demand lift {MARKDOWN_LIFT:.0%}).",
        "- Both policies start with 14 days of stock and draw each delivery's delay from that supplier's real delay "
        "history before the window, so late suppliers are late in the simulation too. One order in flight per product.",
        f"- Manual time saved assumes {MANUAL_MIN_PER_PO} min per manually prepared PO versus {AUTO_MIN_PER_PO} min to review "
        "an AI-prepared one.",
        "- Demand is the store's real daily unit sales; lost sales are not back-ordered.",
        "",
        f"_Runtime {time.perf_counter() - t0:.0f} s._",
    ]
    (OUT / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT / 'evaluation.md'} and 3 charts in {time.perf_counter() - t0:.0f}s")
    for name, (a, bb, fmt, _) in metric.items():
        print(f"  {name}: baseline {fmt.format(a)} | smartstock {fmt.format(bb)}".encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
