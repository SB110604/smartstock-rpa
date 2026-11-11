"""Steps that run after the raw data is generated (model training, first orchestrator run).

Each step is optional at import time so the seed works at every build phase."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session


def after_seed(db: Session, log: Callable[[str], Any]) -> None:
    try:
        from app.agents.orchestrator import run_after_seed
    except ImportError:
        log("  AI pipeline not available yet - skipped")
        return
    run_after_seed(db, log)
