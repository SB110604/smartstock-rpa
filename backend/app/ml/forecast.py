"""Daily demand forecasting (spec 7.3).

Global HistGradientBoostingRegressor across products (product + category as categorical features) with calendar,
festival and lag features, compared on a 28-day holdout against a 28-day moving-average baseline. Each product
keeps whichever method had the lower MAPE. Forecasts are recursive over 30 days with a residual-σ interval."""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.timeutil import now, start_of_day, today
from app.models.ai import Forecast, ModelRegistry
from app.models.catalog import Product
from app.models.core import Festival

logger = logging.getLogger("app.ml.forecast")
MODEL_NAME = "demand_forecast"
HOLDOUT = 28
HORIZON = 30
Z80 = 1.2816  # 80 % two-sided interval
FEATURES = ["product", "category", "festival_id", "dow", "month", "dom", "festival", "days_to_festival", "lag_7", "lag_14", "rm_7", "rm_28"]


# ------------------------------------------------------------------ data

def demand_matrix(db: Session, until: date | None = None, days: int | None = None) -> pd.DataFrame:
    """Units sold per day (rows, local calendar dates up to `until`, default yesterday) × product id (columns)."""
    end = until or today() - timedelta(days=1)
    lower = end - timedelta(days=days - 1) if days else date(1970, 1, 1)
    rows = db.execute(text("""
        SELECT (s.sold_at AT TIME ZONE :tz)::date AS d, l.product_id, SUM(l.qty) AS q
        FROM sale_lines l JOIN sales s ON s.id = l.sale_id
        WHERE s.sold_at >= :lo AND (s.sold_at AT TIME ZONE :tz)::date <= :end
        GROUP BY 1, 2
    """), {"tz": env.TZ, "end": end, "lo": start_of_day(lower) - timedelta(days=1)}).all()
    pids = [p for (p,) in db.execute(select(Product.id).where(Product.is_active.is_(True)).order_by(Product.id))]
    if not rows:
        idx = pd.date_range(end - timedelta(days=(days or 60) - 1), end, freq="D")
        return pd.DataFrame(0.0, index=idx, columns=pids)
    df = pd.DataFrame(rows, columns=["d", "product_id", "q"])
    df["q"] = df["q"].astype(float)
    start = df["d"].min() if days is None else max(df["d"].min(), end - timedelta(days=days - 1))
    idx = pd.date_range(start, end, freq="D")
    m = df.pivot_table(index="d", columns="product_id", values="q", aggfunc="sum")
    m.index = pd.to_datetime(m.index)
    return m.reindex(index=idx, columns=pids, fill_value=0.0).fillna(0.0)


Fests = list[tuple[date, int]]  # (festival date, festival code ≥ 1)


def festival_dates(db: Session) -> Fests:
    rows = sorted(db.execute(select(Festival.date, Festival.name)))
    codes = {name: i + 1 for i, name in enumerate(sorted({n for _, n in rows}))}
    return [(d, codes[n]) for d, n in rows]


def _festival_features(dates: pd.DatetimeIndex, fests: Fests) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """flag = date falls in the 6-day build-up to a festival (or on it); days_to = days until the next festival
    (cap 30); festival_id = which festival is coming (0 when none within 6 days) so Diwali ≠ Navratri."""
    d = dates.values.astype("datetime64[D]")
    if not fests:
        return np.zeros(len(d)), np.full(len(d), 30.0), np.zeros(len(d))
    f = np.array([np.datetime64(x) for x, _ in fests], dtype="datetime64[D]")
    ids = np.array([c for _, c in fests], dtype=float)
    pos = np.searchsorted(f, d)
    has = pos < len(f)
    nxt = np.where(has, f[np.minimum(pos, len(f) - 1)], d + np.timedelta64(365, "D"))
    days_to = (nxt - d).astype(int).clip(0, 30).astype(float)
    flag = (days_to <= 6).astype(float)
    fid = np.where((flag > 0) & has, ids[np.minimum(pos, len(f) - 1)], 0.0)
    return flag, days_to, fid


def _frame(y: pd.DataFrame, rows: pd.DatetimeIndex, fests: Fests, cats: dict[int, int]) -> pd.DataFrame:
    """Feature rows for every (date in `rows`) × product, computed only from values strictly before each date."""
    lag7, lag14 = y.shift(7), y.shift(14)
    rm7 = y.shift(1).rolling(7, min_periods=1).mean()
    rm28 = y.shift(1).rolling(28, min_periods=1).mean()
    flag, days_to, fid = _festival_features(rows, fests)
    cols = list(y.columns)
    n_d, n_p = len(rows), len(cols)
    out = pd.DataFrame({
        "product": np.tile(np.arange(n_p), n_d),
        "category": np.tile([cats.get(p, 0) for p in cols], n_d),
        "festival_id": np.repeat(fid, n_p),
        "dow": np.repeat(rows.dayofweek.values, n_p),
        "month": np.repeat(rows.month.values, n_p),
        "dom": np.repeat(rows.day.values, n_p),
        "festival": np.repeat(flag, n_p),
        "days_to_festival": np.repeat(days_to, n_p),
        "lag_7": lag7.reindex(rows).values.ravel(),
        "lag_14": lag14.reindex(rows).values.ravel(),
        "rm_7": rm7.reindex(rows).values.ravel(),
        "rm_28": rm28.reindex(rows).values.ravel(),
    })
    return out


def _fit(y: pd.DataFrame, fests: Fests, cats: dict[int, int]) -> HistGradientBoostingRegressor:
    rows = y.index[28:]
    x = _frame(y, rows, fests, cats)
    target = y.reindex(rows).values.ravel()
    ok = ~np.isnan(x[["lag_14", "rm_28"]].values).any(axis=1)
    model = HistGradientBoostingRegressor(loss="poisson", max_iter=250, learning_rate=0.06, max_leaf_nodes=31,
                                          min_samples_leaf=40, l2_regularization=0.1,
                                          categorical_features=[0, 1, 2], random_state=42)
    model.fit(x.values[ok], target[ok])
    return model


def recursive_forecast(model: HistGradientBoostingRegressor, history: pd.DataFrame, steps: int, fests: Fests,
                       cats: dict[int, int]) -> pd.DataFrame:
    """Predict `steps` days after the end of `history`, feeding predictions back in for lag/rolling features."""
    y = history.copy()
    start = y.index[-1] + pd.Timedelta(days=1)
    for k in range(steps):
        day = start + pd.Timedelta(days=k)
        y.loc[day] = np.nan
        x = _frame(y, pd.DatetimeIndex([day]), fests, cats)  # features only read rows before `day`
        y.loc[day] = np.maximum(model.predict(x.values), 0.0)
    return y.iloc[len(history):]


# ------------------------------------------------------------------ metrics

def mape(actual: np.ndarray, pred: np.ndarray) -> float | None:
    """Mean absolute percentage error over days with positive sales (%). None if the product never sold."""
    mask = actual > 0
    if not mask.any():
        return None
    return float(np.mean(np.abs(actual[mask] - pred[mask]) / actual[mask]) * 100)


def rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


@dataclass
class Trained:
    version: str
    model: HistGradientBoostingRegressor
    choice: dict[int, str]
    sigma: dict[int, float]
    metrics: dict[str, Any]
    trained_until: date
    per_product: dict[int, dict[str, Any]] = field(default_factory=dict)


def _categories(db: Session) -> dict[int, int]:
    return {pid: cid or 0 for pid, cid in db.execute(select(Product.id, Product.category_id))}


def evaluate_holdout(y: pd.DataFrame, fests: Fests, cats: dict[int, int], holdout: int = HOLDOUT
                     ) -> tuple[pd.DataFrame, pd.DataFrame, HistGradientBoostingRegressor]:
    """Fit on everything before the holdout; return (model predictions, baseline predictions, model)."""
    train_y, test_y = y.iloc[:-holdout], y.iloc[-holdout:]
    model = _fit(train_y, fests, cats)
    pred = recursive_forecast(model, train_y, holdout, fests, cats)
    pred.index = test_y.index
    base = pd.DataFrame(np.tile(train_y.tail(28).mean().values, (holdout, 1)), index=test_y.index, columns=y.columns)
    return pred, base, model


def train(db: Session, holdout: int = HOLDOUT, until: date | None = None) -> Trained:
    y = demand_matrix(db, until=until)
    if len(y) < holdout + 60:
        raise ValueError(f"Need at least {holdout + 60} days of sales history to train (have {len(y)})")
    fests = festival_dates(db)
    cats = _categories(db)
    pred, base, _ = evaluate_holdout(y, fests, cats, holdout)
    test_y = y.iloc[-holdout:]
    choice, sigma, per = {}, {}, {}
    m_mapes, b_mapes, chosen_mapes, m_rmse, b_rmse = [], [], [], [], []
    for p in y.columns:
        a, fm, fb = test_y[p].values, pred[p].values, base[p].values
        mm, mb = mape(a, fm), mape(a, fb)
        rm, rb = rmse(a, fm), rmse(a, fb)
        use_model = mm is not None and (mb is None or mm <= mb)
        choice[int(p)] = "hgb" if use_model else "ma28"
        resid = a - (fm if use_model else fb)
        sigma[int(p)] = float(np.std(resid)) if len(resid) > 1 else 0.0
        per[int(p)] = {"mape_model": mm, "mape_baseline": mb, "rmse_model": rm, "rmse_baseline": rb,
                       "choice": choice[int(p)]}
        if mm is not None:
            m_mapes.append(mm)
        if mb is not None:
            b_mapes.append(mb)
        if (mm if use_model else mb) is not None:
            chosen_mapes.append(mm if use_model else mb)
        m_rmse.append(rm)
        b_rmse.append(rb)
    final = _fit(y, fests, cats)  # retrain on all data for forecasting
    version = now().strftime("v%Y%m%d-%H%M%S")
    metrics = {
        "mape": round(float(np.mean(chosen_mapes)), 2) if chosen_mapes else None,
        "mape_model": round(float(np.mean(m_mapes)), 2) if m_mapes else None,
        "mape_baseline": round(float(np.mean(b_mapes)), 2) if b_mapes else None,
        "rmse_model": round(float(np.mean(m_rmse)), 3),
        "rmse_baseline": round(float(np.mean(b_rmse)), 3),
        "products_model": sum(1 for c in choice.values() if c == "hgb"),
        "products_baseline": sum(1 for c in choice.values() if c == "ma28"),
        "holdout_days": holdout,
        "train_days": len(y),
        "holdout_start": str(test_y.index[0].date()),
        "holdout_end": str(test_y.index[-1].date()),
    }
    return Trained(version, final, choice, sigma, metrics, y.index[-1].date(), per)


def save(db: Session, t: Trained, activate: bool, notes: str | None = None) -> ModelRegistry:
    folder = env.storage_subdir("models")
    path = folder / f"{MODEL_NAME}_{t.version}.joblib"
    joblib.dump({"model": t.model, "choice": t.choice, "sigma": t.sigma, "features": FEATURES,
                 "trained_until": t.trained_until, "per_product": t.per_product}, path)
    if activate:
        for m in db.scalars(select(ModelRegistry).where(ModelRegistry.name == MODEL_NAME, ModelRegistry.is_active.is_(True))):
            m.is_active = False
    reg = ModelRegistry(name=MODEL_NAME, version=t.version, trained_at=now(), metrics=t.metrics, is_active=activate,
                        file_path=str(path), notes=notes)
    db.add(reg)
    db.flush()
    return reg


def active(db: Session) -> ModelRegistry | None:
    return db.scalar(select(ModelRegistry).where(ModelRegistry.name == MODEL_NAME, ModelRegistry.is_active.is_(True))
                     .order_by(ModelRegistry.trained_at.desc()))


def load(reg: ModelRegistry) -> dict[str, Any] | None:
    if not reg.file_path or not Path(reg.file_path).exists():
        return None
    return joblib.load(reg.file_path)


def write_forecasts(db: Session, reg: ModelRegistry, art: dict[str, Any], horizon: int = HORIZON) -> int:
    """Forecast `horizon` days from today using the active model artefact and store them (replacing future rows)."""
    y = demand_matrix(db)
    fests = festival_dates(db)
    cats = _categories(db)
    model_pred = recursive_forecast(art["model"], y, horizon, fests, cats)
    ma = y.tail(28).mean()
    db.execute(delete(Forecast).where(Forecast.date >= today()))
    rows = []
    for p in y.columns:
        method = art["choice"].get(int(p), "ma28")
        sigma = float(art["sigma"].get(int(p), 0.0))
        for d, v in zip(model_pred.index, model_pred[p].values, strict=True):
            f = float(v) if method == "hgb" else float(ma[p])
            rows.append({"product_id": int(p), "date": d.date(), "predicted_qty": round(f, 3),
                         "lower": round(max(0.0, f - Z80 * sigma), 3), "upper": round(f + Z80 * sigma, 3),
                         "model_name": method, "model_version": reg.version})
    if rows:
        db.execute(Forecast.__table__.insert(), rows)
    return len(rows)


def ensure_model(db: Session) -> tuple[ModelRegistry, dict[str, Any]]:
    """Active model + artefact; trains and activates one if none exists (first run / fresh install)."""
    reg = active(db)
    art = load(reg) if reg else None
    if reg is None or art is None:
        t = train(db)
        reg = save(db, t, activate=True, notes="initial model")
        art = load(reg)
        assert art is not None
    return reg, art


def forecasts_for(db: Session, product_id: int, days: int | None = None) -> list[Forecast]:
    stmt = select(Forecast).where(Forecast.product_id == product_id, Forecast.date >= today()).order_by(Forecast.date)
    if days:
        stmt = stmt.where(Forecast.date < today() + timedelta(days=days))
    return list(db.scalars(stmt))


def latest_forecast_date(db: Session) -> datetime | None:
    return db.scalar(select(func.max(Forecast.created_at)))
