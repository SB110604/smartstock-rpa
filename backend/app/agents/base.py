"""Agent contract (spec 7): each agent is a class with run(context) -> AgentResult, logged to agent_runs."""

import logging
import traceback
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import log_ctx
from app.core.timeutil import now, today
from app.models.ai import AgentRun
from app.services import settings as settings_svc

logger = logging.getLogger("app.agents")


@dataclass
class AgentResult:
    items_processed: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)  # handed to later agents in the pipeline (not persisted)


@dataclass
class AgentContext:
    db: Session
    triggered_by: str = "schedule"
    pipeline_id: str | None = None
    day: date = field(default_factory=today)
    results: dict[str, AgentResult] = field(default_factory=dict)
    _settings: dict[str, Any] | None = None

    @property
    def settings(self) -> dict[str, Any]:
        if self._settings is None:
            self._settings = settings_svc.get_all(self.db)
        return self._settings


class Agent:
    name = "agent"
    title = "Agent"
    description = ""

    def run(self, ctx: AgentContext) -> AgentResult:
        raise NotImplementedError


def execute(agent: Agent, ctx: AgentContext) -> tuple[AgentRun, AgentResult | None]:
    """Run one agent inside its own transaction; failures are recorded and never propagate."""
    db = ctx.db
    run = AgentRun(agent_name=agent.name, started_at=now(), status="running", triggered_by=ctx.triggered_by,
                   pipeline_id=ctx.pipeline_id)
    db.add(run)
    db.commit()
    try:
        result = agent.run(ctx)
        run.status, run.items_processed, run.summary_json = "success", result.items_processed, result.summary
        run.finished_at = now()
        db.commit()
        ctx.results[agent.name] = result
        logger.info("agent finished", extra=log_ctx(agent=agent.name, items=result.items_processed))
        return run, result
    except Exception as exc:  # isolate failures: the pipeline continues with the next agent
        db.rollback()
        run = db.merge(run)
        run.status, run.finished_at = "failed", now()
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.summary_json = {"trace": traceback.format_exc(limit=4)[-1500:]}
        db.commit()
        logger.exception("agent failed", extra=log_ctx(agent=agent.name))
        return run, None
