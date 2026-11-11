"""Orchestrator (spec 7): daily pipeline StockMonitor → Expiry → Decision → Supplier → AutoOrder → Tracking → Anomaly.

Each agent runs in its own transaction and is logged to agent_runs; one agent failing never stops the rest.
`run_agent` powers the admin "Run now" button and runs an agent's prerequisites first when it needs their output."""

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agents.anomaly import AnomalyAgent
from app.agents.auto_order import AutoOrderAgent
from app.agents.base import Agent, AgentContext, execute
from app.agents.decision import DecisionAgent
from app.agents.expiry import ExpiryAgent
from app.agents.learning import LearningAgent
from app.agents.stock_monitor import StockMonitorAgent
from app.agents.supplier import SupplierAgent
from app.agents.tracking import TrackingAgent
from app.core.errors import NotFound
from app.core.timeutil import today
from app.services import supplier_scoring

PIPELINE: list[Agent] = [StockMonitorAgent(), ExpiryAgent(), DecisionAgent(), SupplierAgent(), AutoOrderAgent(),
                         TrackingAgent(), AnomalyAgent()]
AGENTS: dict[str, Agent] = {a.name: a for a in PIPELINE}
AGENTS["learning"] = LearningAgent()  # weekly retraining + daily accuracy/drift; not part of the 06:00 pipeline
DEPENDS: dict[str, list[str]] = {"supplier": ["decision"], "auto_order": ["decision", "supplier"]}


def _summary(ctx: AgentContext, runs: list[Any]) -> dict[str, Any]:
    return {"pipeline_id": ctx.pipeline_id, "runs": [{"agent": r.agent_name, "status": r.status, "summary": r.summary_json,
                                                      "error": r.error, "items": r.items_processed} for r in runs]}


def run_pipeline(db: Session, triggered_by: str = "schedule", agents: list[str] | None = None) -> dict[str, Any]:
    ctx = AgentContext(db=db, triggered_by=triggered_by, pipeline_id=uuid.uuid4().hex[:12])
    runs = []
    for agent in PIPELINE:
        if agents and agent.name not in agents:
            continue
        run, _ = execute(agent, ctx)
        runs.append(run)
    return _summary(ctx, runs)


def run_agent(db: Session, name: str, triggered_by: str = "manual") -> dict[str, Any]:
    if name not in AGENTS:
        raise NotFound(f"Unknown agent '{name}'")
    ctx = AgentContext(db=db, triggered_by=triggered_by, pipeline_id=uuid.uuid4().hex[:12])
    runs = []
    for dep in DEPENDS.get(name, []):
        run, _ = execute(AGENTS[dep], ctx)
        runs.append(run)
    run, _ = execute(AGENTS[name], ctx)
    runs.append(run)
    return _summary(ctx, runs)


def quick_check(db: Session) -> dict[str, Any]:
    """Every 2 hours 08:00–22:00: stock monitor + expiry only."""
    return run_pipeline(db, "quick_check", ["stock_monitor", "expiry"])


def run_after_seed(db: Session, log: Callable[[str], Any]) -> None:
    """Spec 11: after seeding, train models and run the orchestrator once so dashboards are populated."""
    for months_back in range(6, 0, -1):  # supplier score history for trend charts
        supplier_scoring.compute_scores(db, as_of=today() - timedelta(days=30 * months_back))
    db.commit()
    result = run_pipeline(db, "seed")
    # reorder points exist only after the Decision agent ran, so re-check stock and expiry once more
    result["runs"] += quick_check(db)["runs"]
    for r in result["runs"]:
        log(f"  agent {r['agent']}: {r['status']}" + (f" ({r['error']})" if r["error"] else ""))
    run, _ = execute(AGENTS["learning"], AgentContext(db=db, triggered_by="seed", pipeline_id=result["pipeline_id"]))
    log(f"  agent learning: {run.status}")
