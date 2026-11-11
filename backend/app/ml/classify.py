"""ABC (12-month revenue: A = top 80 %, B = next 15 %, C = rest) and XYZ (CV of weekly demand) — spec 7.1."""

from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.timeutil import today
from app.ml.forecast import demand_matrix


def abc(revenue: dict[int, float]) -> dict[int, str]:
    total = sum(max(v, 0) for v in revenue.values())
    if total <= 0:
        return {p: "C" for p in revenue}
    out, cum = {}, 0.0
    for i, (p, v) in enumerate(sorted(revenue.items(), key=lambda kv: kv[1], reverse=True)):
        cum += max(v, 0)
        share = cum / total  # cumulative share including this item
        out[p] = "A" if share <= 0.80 + 1e-9 or i == 0 else ("B" if share <= 0.95 + 1e-9 else "C")
    return out


def xyz(weekly: pd.DataFrame) -> dict[int, str]:
    """weekly: rows = weeks, columns = product ids. CV = σ / μ of weekly units (no sales → Z)."""
    out = {}
    for p in weekly.columns:
        s = weekly[p].values.astype(float)
        mu = s.mean()
        cv = float(s.std() / mu) if mu > 0 else np.inf
        out[int(p)] = "X" if cv < 0.5 else ("Y" if cv < 1.0 else "Z")
    return out


def compute(db: Session) -> dict[int, tuple[str, str]]:
    start = today() - timedelta(days=365)
    rev = dict(db.execute(text("""
        SELECT l.product_id, SUM(l.line_total) FROM sale_lines l JOIN sales s ON s.id = l.sale_id
        WHERE (s.sold_at AT TIME ZONE :tz)::date >= :start GROUP BY 1
    """), {"tz": env.TZ, "start": start}).all())
    y = demand_matrix(db, days=364)
    weekly = y.resample("W").sum()
    for p in y.columns:
        rev.setdefault(int(p), 0.0)
    a = abc({int(k): float(v or 0) for k, v in rev.items()})
    x = xyz(weekly)
    return {p: (a.get(p, "C"), x.get(p, "Z")) for p in set(a) | set(x)}
