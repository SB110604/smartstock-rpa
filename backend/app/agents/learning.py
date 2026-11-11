"""Continuous-learning agent (spec 7.9): accuracy tracking, drift alerts, weekly retrain with promotion."""

from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentResult
from app.ml import learning as ml_learning
from app.models.catalog import Product
from app.services import alerts
from app.services import learning as feedback


class LearningAgent(Agent):
    name = "learning"
    title = "Continuous learning"
    description = "Tracks realised forecast accuracy, raises drift alerts and retrains weekly, promoting only better models."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        summary: dict = {}
        if ctx.triggered_by == "seed":
            summary["backfilled_days"] = ml_learning.backfill_history(db)
        acc = ml_learning.record_accuracy(db)
        summary["yesterday_mape"] = acc.mape if acc else None
        if ctx.triggered_by in ("weekly", "manual"):
            try:
                summary["retrain"] = ml_learning.retrain(db)
            except ValueError as exc:  # not enough history yet — keep the current model
                summary["retrain"] = {"skipped": str(exc)}
        drift = ml_learning.drift_status(db)
        summary["drift"] = drift
        if drift["drift"]:
            alerts.raise_alert(db, "forecast_drift",
                               f"Forecast accuracy drifted: rolling {ml_learning.DRIFT_WINDOW}-day MAPE {drift['rolling_mape']}% "
                               f"is above 1.5× the training MAPE ({drift['training_mape']}%). Retraining is recommended.",
                               severity="warning", key="forecast_drift", data=drift)
        else:
            alerts.resolve_by_key(db, "forecast_drift", "accuracy back within limits")
        products = list(db.scalars(select(Product.id).where(Product.is_active.is_(True))))
        factors = {p: feedback.correction_factor(db, p) for p in products}
        summary["products_with_correction"] = sum(1 for f in factors.values() if abs(f - 1) >= 0.01)
        db.flush()
        return AgentResult(items_processed=len(products), summary=summary)
