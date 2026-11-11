"""Supplier agent (spec 7.4): recompute supplier scores and pick the best supplier per recommended product."""

from datetime import timedelta

from sqlalchemy import func, select

from app.agents.base import Agent, AgentContext, AgentResult
from app.core.timeutil import now
from app.models.ai import SupplierScore
from app.services import supplier_scoring


class SupplierAgent(Agent):
    name = "supplier"
    title = "Supplier"
    description = "Scores suppliers on price, on-time delivery, lead time and quality, and picks the best one per product."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        latest = db.scalar(select(func.max(SupplierScore.computed_at)))
        recomputed = 0
        if latest is None or latest < now() - timedelta(hours=20) or ctx.triggered_by in ("nightly", "manual"):
            recomputed = len(supplier_scoring.compute_scores(db))
        recs = (ctx.results.get("decision").data.get("recommendations", []) if ctx.results.get("decision") else [])
        stats = supplier_scoring.delivery_stats(db)
        w = supplier_scoring.weights(db)
        changed = 0
        for r in recs:
            choice = supplier_scoring.rank_for_product(db, r["product_id"], stats, w)
            if not choice:
                continue
            if choice.supplier_id != r.get("supplier_id"):
                changed += 1
            r["supplier_id"] = choice.supplier_id
            r["unit_price"] = choice.unit_price
            r["reason_json"]["supplier"] = {"id": choice.supplier_id, "name": choice.supplier_name, "score": choice.score,
                                            "breakdown": choice.breakdown, "alternatives": choice.alternatives[:4],
                                            "weights": w}
            r["reason_text"] += (f" Best supplier: {choice.supplier_name} (score {choice.score:.0f}/100, "
                                 f"₹{choice.unit_price:g}, ~{choice.lead_days:g} days).")
        db.flush()
        return AgentResult(items_processed=len(recs) + recomputed,
                           summary={"scores_recomputed": recomputed, "recommendations_scored": len(recs),
                                    "supplier_changed": changed},
                           data={"recommendations": recs})
