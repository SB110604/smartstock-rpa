"""AI Insights: agents and runs, forecasts, ABC/XYZ, dead stock, model registry, expiry assessment."""

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.agents import orchestrator
from app.core.deps import DB, require
from app.core.errors import Forbidden
from app.core.pagination import PageParams, page_params, paginate
from app.core.permissions import allowed
from app.core.timeutil import today
from app.ml import forecast
from app.models.ai import AgentRun, Alert, ModelRegistry
from app.models.catalog import Product
from app.models.core import User
from app.services import expiry, performance, stock

router = APIRouter(tags=["ai insights"])
Insights = Annotated[User, Depends(require("insights.read"))]
Runner = Annotated[User, Depends(require("agents.run"))]
StockReader = Annotated[User, Depends(require("stock.read"))]
ProductReader = Annotated[User, Depends(require("products.read"))]


def run_out(r: AgentRun) -> dict[str, Any]:
    secs = (r.finished_at - r.started_at).total_seconds() if r.finished_at else None
    return {"id": r.id, "agent": r.agent_name, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at,
            "seconds": round(secs, 1) if secs is not None else None, "items": r.items_processed, "summary": r.summary_json,
            "error": r.error, "triggered_by": r.triggered_by, "pipeline_id": r.pipeline_id}


@router.get("/agents")
def agents(user: Insights, db: DB) -> list[dict[str, Any]]:
    pipeline = [a.name for a in orchestrator.PIPELINE]
    out = []
    for name, a in orchestrator.AGENTS.items():
        last = db.scalar(select(AgentRun).where(AgentRun.agent_name == name).order_by(AgentRun.id.desc()))
        ok = db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.agent_name == name, AgentRun.status == "success"))
        out.append({"name": name, "title": a.title, "description": a.description, "in_pipeline": name in pipeline,
                    "order": pipeline.index(name) + 1 if name in pipeline else None,
                    "last_run": run_out(last) if last else None, "successful_runs": ok or 0})
    return out


@router.get("/agent-runs")
def agent_runs(user: Insights, db: DB, p: Annotated[PageParams, Depends(page_params)], agent: str | None = None,
               status: str | None = None) -> dict[str, Any]:
    stmt = select(AgentRun)
    if agent:
        stmt = stmt.where(AgentRun.agent_name == agent)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    return paginate(db, stmt.order_by(AgentRun.id.desc()), p, run_out)


@router.post("/agents/pipeline/run")
def run_pipeline(user: Runner, db: DB) -> dict[str, Any]:
    return orchestrator.run_pipeline(db, "manual")


@router.post("/agents/{name}/run")
def run_agent(name: str, user: Runner, db: DB) -> dict[str, Any]:
    if name == "learning" and not allowed(user.role, "models.retrain"):
        raise Forbidden("Only an admin can retrain models")
    return orchestrator.run_agent(db, name, "manual")


@router.get("/products/{product_id}/forecast")
def product_forecast(product_id: int, user: ProductReader, db: DB, history_days: int = 60) -> dict[str, Any]:
    stock.get_product(db, product_id)
    hist = forecast.demand_matrix(db, days=history_days)
    actual = [{"date": d.date(), "actual": float(v)} for d, v in hist[product_id].items()] if product_id in hist else []
    fcs = forecast.forecasts_for(db, product_id)
    reg = forecast.active(db)
    per = None
    if reg:
        art = forecast.load(reg)
        per = (art or {}).get("per_product", {}).get(product_id)
    return {"actual": actual,
            "forecast": [{"date": f.date, "predicted": f.predicted_qty, "lower": f.lower, "upper": f.upper} for f in fcs],
            "model": fcs[0].model_name if fcs else None, "model_version": reg.version if reg else None,
            "accuracy": per, "next_7_days": round(sum(f.predicted_qty for f in fcs[:7]), 1),
            "next_30_days": round(sum(f.predicted_qty for f in fcs), 1)}


@router.get("/insights/abc-xyz")
def abc_xyz(user: Insights, db: DB) -> dict[str, Any]:
    levels = stock.levels(db)
    cells: dict[str, dict[str, Any]] = {f"{a}{x}": {"count": 0, "value": 0.0, "products": []} for a in "ABC" for x in "XYZ"}
    for p in db.scalars(select(Product).where(Product.is_active.is_(True)).order_by(Product.name)).unique():
        if not p.abc_class or not p.xyz_class:
            continue
        c = cells[f"{p.abc_class}{p.xyz_class}"]
        value = levels.get(p.id, {}).get("on_hand", 0.0) * p.cost_price
        c["count"] += 1
        c["value"] = round(c["value"] + value, 2)
        c["products"].append({"id": p.id, "name": p.name, "sku": p.sku})
    advice = {"AX": "Tight control, frequent small orders", "AY": "Safety stock + close review", "AZ": "Order to demand, monitor",
              "BX": "Periodic review", "BY": "Standard policy", "BZ": "Buffer stock",
              "CX": "Bulk, infrequent orders", "CY": "Minimal attention", "CZ": "Consider delisting / order on demand"}
    return {"cells": cells, "advice": advice}


@router.get("/insights/dead-stock")
def dead_stock(user: Insights, db: DB) -> list[dict[str, Any]]:
    rows = db.scalars(select(Alert).where(Alert.type == "dead_stock", Alert.status.in_(("open", "acknowledged")))
                      .order_by(Alert.created_at.desc()))
    names = dict(db.execute(select(Product.id, Product.name)).all())
    return [{"alert_id": a.id, "product_id": a.product_id, "product": names.get(a.product_id or 0), "message": a.message,
             **(a.data_json or {})} for a in rows]


@router.get("/insights/performance")
def ai_performance(user: Insights, db: DB) -> dict[str, Any]:
    return performance.overview(db)


@router.get("/models")
def models(user: Insights, db: DB) -> list[dict[str, Any]]:
    rows = db.scalars(select(ModelRegistry).order_by(ModelRegistry.trained_at.desc()).limit(50))
    return [{"id": m.id, "name": m.name, "version": m.version, "trained_at": m.trained_at, "metrics": m.metrics,
             "is_active": m.is_active, "notes": m.notes} for m in rows]


@router.get("/expiry")
def expiry_overview(user: StockReader, db: DB, location_id: int | None = None) -> dict[str, Any]:
    rows = [r for r in expiry.assess(db) if not location_id or r["location_id"] == location_id]
    groups: dict[str, list[dict[str, Any]]] = {"expired": [], "critical": [], "warning": []}
    for r in rows:
        if r["bucket"] in groups:
            groups[r["bucket"]].append(r)
    by_week: dict[str, float] = {}
    for r in expiry.assess(db, include_ok=True):
        if 0 < r["days_to_expiry"] <= 56:
            wk = (today() + timedelta(days=r["days_to_expiry"])).strftime("%G-W%V")
            by_week[wk] = round(by_week.get(wk, 0.0) + r["value"], 2)
    return {"groups": groups,
            "totals": {k: {"batches": len(v), "value": round(sum(x["value"] for x in v), 2),
                           "at_risk": sum(1 for x in v if x["at_risk"])} for k, v in groups.items()},
            "value_by_week": [{"week": k, "value": v} for k, v in sorted(by_week.items())]}
