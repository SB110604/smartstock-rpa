"""Model lifecycle for continuous learning (spec 7.9): realised accuracy, drift detection, retrain-and-promote."""

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.timeutil import today
from app.ml import forecast
from app.models.ai import Forecast, ForecastAccuracy, ModelRegistry

DRIFT_WINDOW = 14
DRIFT_FACTOR = 1.5


def record_accuracy(db: Session, day: date | None = None) -> ForecastAccuracy | None:
    """MAPE of the stored forecast for `day` (default yesterday) against actual sales; one row per day."""
    d = day or today() - timedelta(days=1)
    fc = {f.product_id: f for f in db.scalars(select(Forecast).where(Forecast.date == d))}
    if not fc:
        return None
    y = forecast.demand_matrix(db, until=d, days=1)
    actual = {int(p): float(y[p].iloc[-1]) for p in y.columns} if len(y) else {}
    errs = [abs(actual.get(p, 0.0) - f.predicted_qty) / actual[p] for p, f in fc.items() if actual.get(p, 0) > 0]
    if not errs:
        return None
    db.execute(delete(ForecastAccuracy).where(ForecastAccuracy.date == d))
    version = next(iter(fc.values())).model_version
    row = ForecastAccuracy(date=d, mape=round(float(np.mean(errs)) * 100, 2), products=len(errs), model_version=version,
                           detail={"wape": round(sum(abs(actual.get(p, 0) - f.predicted_qty) for p, f in fc.items())
                                                 / max(1e-9, sum(actual.get(p, 0) for p in fc)) * 100, 2)})
    db.add(row)
    db.flush()
    return row


def rolling_mape(db: Session, days: int = DRIFT_WINDOW) -> float | None:
    rows = list(db.scalars(select(ForecastAccuracy.mape).where(ForecastAccuracy.date >= today() - timedelta(days=days))))
    return round(float(np.mean(rows)), 2) if rows else None


def drift_status(db: Session) -> dict[str, Any]:
    reg = forecast.active(db)
    rolling = rolling_mape(db)
    train = (reg.metrics or {}).get("mape") if reg else None
    drift = bool(rolling is not None and train and rolling > DRIFT_FACTOR * train)
    return {"rolling_mape": rolling, "training_mape": train, "threshold": round(DRIFT_FACTOR * train, 2) if train else None,
            "drift": drift, "model_version": reg.version if reg else None}


def evaluate_artifact(art: dict[str, Any], y: pd.DataFrame, fests: forecast.Fests, cats: dict[int, int],
                      holdout: int = forecast.HOLDOUT) -> float | None:
    """Chosen-method MAPE of an existing model artefact on the last `holdout` days of `y` (same window as a new model)."""
    train_y, test_y = y.iloc[:-holdout], y.iloc[-holdout:]
    pred = forecast.recursive_forecast(art["model"], train_y, holdout, fests, cats)
    ma = train_y.tail(28).mean()
    mapes = []
    for p in y.columns:
        f = pred[p].values if art["choice"].get(int(p), "ma28") == "hgb" else np.full(holdout, ma[p])
        m = forecast.mape(test_y[p].values, f)
        if m is not None:
            mapes.append(m)
    return round(float(np.mean(mapes)), 2) if mapes else None


def retrain(db: Session) -> dict[str, Any]:
    """Weekly: train a challenger, compare with the active model on the same holdout, promote only if better."""
    challenger = forecast.train(db)
    current = forecast.active(db)
    current_art = forecast.load(current) if current else None
    current_mape = None
    if current_art:
        y = forecast.demand_matrix(db)
        current_mape = evaluate_artifact(current_art, y, forecast.festival_dates(db), forecast._categories(db))
    new_mape = challenger.metrics.get("mape")
    promote = current is None or current_mape is None or (new_mape is not None and new_mape < current_mape)
    challenger.metrics["compared_with"] = current.version if current else None
    challenger.metrics["incumbent_mape_same_holdout"] = current_mape
    note = (f"promoted: MAPE {new_mape} < {current_mape} (incumbent {current.version})" if promote and current
            else "initial model" if promote else f"kept incumbent {current.version}: MAPE {new_mape} ≥ {current_mape}")
    reg = forecast.save(db, challenger, activate=promote, notes=note)
    if promote:
        art = forecast.load(reg)
        if art:
            forecast.write_forecasts(db, reg, art)
    return {"challenger": reg.version, "challenger_mape": new_mape, "incumbent": current.version if current else None,
            "incumbent_mape": current_mape, "promoted": promote, "note": note}


def backfill_history(db: Session, weeks: int = 8) -> int:
    """Seed helper: rolling-origin backtest for the last `weeks` weeks so the accuracy trend has history.
    One model is trained on the data before the first week; each week is then forecast from the actuals up to it."""
    y = forecast.demand_matrix(db)
    fests, cats = forecast.festival_dates(db), forecast._categories(db)
    rows = 0
    first = len(y) - 7 * weeks
    if first < 120:
        return 0
    model = forecast._fit(y.iloc[:first], fests, cats)
    for w in range(weeks, 0, -1):
        cut = len(y) - 7 * w
        hist = y.iloc[:cut]
        pred = forecast.recursive_forecast(model, hist, 7, fests, cats)
        version = f"backtest-{hist.index[-1]:%Y%m%d}"
        recs = []
        for d, r in pred.iterrows():
            for p, v in r.items():
                recs.append({"product_id": int(p), "date": d.date(), "predicted_qty": round(float(v), 3),
                             "lower": 0.0, "upper": round(float(v) * 2, 3), "model_name": "hgb", "model_version": version})
        db.execute(delete(Forecast).where(Forecast.date.in_([d.date() for d in pred.index])))
        db.execute(Forecast.__table__.insert(), recs)
        for d in pred.index:
            if record_accuracy(db, d.date()):
                rows += 1
    return rows


def model_history(db: Session) -> list[ModelRegistry]:
    return list(db.scalars(select(ModelRegistry).where(ModelRegistry.name == forecast.MODEL_NAME)
                           .order_by(ModelRegistry.trained_at)))
