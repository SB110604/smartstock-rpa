"""AI Performance page data (spec 7.9): accuracy trend, acceptance rate, quantity correction, model versions."""

from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import local_date, today
from app.ml import learning
from app.models.ai import Feedback, ForecastAccuracy
from app.models.purchasing import PurchaseRequest


def overview(db: Session, weeks: int = 16) -> dict[str, Any]:
    since = today() - timedelta(weeks=weeks)
    acc = list(db.scalars(select(ForecastAccuracy).where(ForecastAccuracy.date >= since).order_by(ForecastAccuracy.date)))
    rows = db.execute(select(Feedback.decision, Feedback.suggested_qty, Feedback.final_qty, Feedback.created_at)
                      .join(PurchaseRequest, PurchaseRequest.id == Feedback.purchase_request_id)
                      .where(PurchaseRequest.created_by == "agent", Feedback.created_at >= since)).all()
    weekly: dict[str, dict[str, float]] = defaultdict(lambda: {"total": 0, "accepted": 0, "as_is": 0, "ratio_sum": 0.0,
                                                               "ratio_n": 0})
    for decision, suggested, final, at in rows:
        wk = local_date(at).strftime("%G-W%V")
        w = weekly[wk]
        w["total"] += 1
        if decision in ("approved", "edited"):
            w["accepted"] += 1
            if final and suggested:
                w["ratio_sum"] += final / suggested
                w["ratio_n"] += 1
        if decision == "approved":
            w["as_is"] += 1
    trend = [{"week": k, "suggestions": int(v["total"]),
              "acceptance_pct": round(100 * v["accepted"] / v["total"], 1) if v["total"] else None,
              "accepted_as_is_pct": round(100 * v["as_is"] / v["total"], 1) if v["total"] else None,
              "avg_correction": round(v["ratio_sum"] / v["ratio_n"], 3) if v["ratio_n"] else None}
             for k, v in sorted(weekly.items())]
    total = sum(v["total"] for v in weekly.values())
    accepted = sum(v["accepted"] for v in weekly.values())
    ratio_n = sum(v["ratio_n"] for v in weekly.values())
    models = learning.model_history(db)
    return {
        "accuracy": [{"date": a.date, "mape": a.mape, "model_version": a.model_version} for a in acc],
        "drift": learning.drift_status(db),
        "suggestions": trend,
        "totals": {"suggestions": total, "acceptance_pct": round(100 * accepted / total, 1) if total else None,
                   "avg_correction": round(sum(v["ratio_sum"] for v in weekly.values()) / ratio_n, 3) if ratio_n else None,
                   "rejected": total - accepted},
        "models": [{"version": m.version, "trained_at": m.trained_at, "is_active": m.is_active, "notes": m.notes,
                    "mape": (m.metrics or {}).get("mape"), "mape_baseline": (m.metrics or {}).get("mape_baseline"),
                    "incumbent_mape": (m.metrics or {}).get("incumbent_mape_same_holdout")} for m in models],
    }
