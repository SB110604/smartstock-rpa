"""Anomaly detection (spec 7.7): explicit rule checks plus an IsolationForest on stock-movement features."""

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.timeutil import TZ, now, today
from app.models.ai import ModelRegistry
from app.models.catalog import Product
from app.models.core import AuditLog, User
from app.models.inventory import StockMovement

MODEL_NAME = "movement_anomaly"
LOOKBACK_DAYS = 7


@dataclass
class Finding:
    rule: str
    key: str  # de-dup key
    message: str
    severity: str = "warning"
    product_id: int | None = None
    ref_type: str | None = None
    ref_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


def _since() -> Any:
    return now() - timedelta(days=LOOKBACK_DAYS)


def _names(db: Session) -> tuple[dict[int, str], dict[int, str]]:
    products = {int(i): n for i, n in db.execute(select(Product.id, Product.name))}
    users = {int(i): n for i, n in db.execute(select(User.id, User.name))}
    return products, users


def big_adjustments(db: Session, sigma: float = 3.0, min_history: int = 5) -> list[Finding]:
    """Recent adjustment whose size is beyond 3σ of that product's previous adjustments."""
    out = []
    recent = db.scalars(select(StockMovement).where(StockMovement.type == "adjustment", StockMovement.created_at >= _since(),
                                                    StockMovement.reference_type == "adjustment"))
    for m in recent.unique():
        hist = [q for (q,) in db.execute(select(StockMovement.qty).where(
            StockMovement.product_id == m.product_id, StockMovement.type == "adjustment",
            StockMovement.reference_type == "adjustment", StockMovement.id != m.id, StockMovement.created_at < m.created_at))]
        if len(hist) < min_history:
            continue
        mu, sd = float(np.mean(hist)), float(np.std(hist))
        limit = sigma * sd if sd > 0 else sigma * max(1.0, float(np.mean(np.abs(hist))))
        if abs(m.qty - mu) > limit:
            out.append(Finding("big_adjustment", f"anomaly:adj:{m.id}",
                               f"Stock adjustment of {m.qty:+g} {m.product.unit} on {m.product.name} is beyond 3σ of its usual "
                               f"corrections (mean {mu:+.1f}, σ {sd:.1f}). Value ₹{abs(m.qty) * m.unit_cost:,.0f}.",
                               "critical", m.product_id, "stock_movement", m.id,
                               {"qty": m.qty, "mean": mu, "sigma": sd, "user_id": m.user_id, "rule": "adjustment > 3σ"}))
    return out


def negative_stock_attempts(db: Session) -> list[Finding]:
    rows = db.execute(select(AuditLog.user_id, AuditLog.entity_id, AuditLog.id).where(
        AuditLog.action == "negative_stock_attempt", AuditLog.created_at >= _since())).all()
    groups: dict[tuple[int | None, str | None], list[int]] = {}
    for uid, pid, aid in rows:
        groups.setdefault((uid, pid), []).append(aid)
    out = []
    products, users = _names(db)
    for (uid, pid), ids in groups.items():
        pname = products.get(int(pid), f"product #{pid}") if pid and pid.isdigit() else f"product #{pid}"
        out.append(Finding("negative_stock", f"anomaly:neg:{uid}:{pid}",
                           f"{len(ids)} attempt(s) to issue more {pname} than available by {users.get(uid or 0, 'an unknown user')} in the "
                           f"last {LOOKBACK_DAYS} days — check for unrecorded receipts or wrong scans.",
                           "warning", int(pid) if pid and pid.isdigit() else None, "audit_log", ids[-1],
                           {"attempts": len(ids), "user_id": uid}))
    return out


def cost_changes(db: Session, threshold_pct: float = 20.0) -> list[Finding]:
    out = []
    products, _ = _names(db)
    for a in db.scalars(select(AuditLog).where(AuditLog.entity == "products", AuditLog.action == "update",
                                               AuditLog.created_at >= _since())):
        b, c = (a.before_json or {}).get("cost_price"), (a.after_json or {}).get("cost_price")
        if b and c is not None and b > 0:
            pct = (c - b) / b * 100
            if abs(pct) > threshold_pct:
                pid = int(a.entity_id) if a.entity_id and a.entity_id.isdigit() else None
                out.append(Finding("cost_change", f"anomaly:cost:{a.id}",
                                   f"Cost price of {products.get(pid or 0, f'product #{pid}')} changed {pct:+.0f}% (₹{b:g} → ₹{c:g}). Verify the supplier "
                                   "invoice before it affects margins and reorder value.", "warning", pid, "audit_log", a.id,
                                   {"before": b, "after": c, "pct": round(pct, 1), "user_id": a.user_id}))
    return out


def sales_spikes(db: Session, factor: float = 3.0, min_units: float = 10) -> list[Finding]:
    rows = db.execute(text("""
        SELECT (s.sold_at AT TIME ZONE :tz)::date d, l.product_id, SUM(l.qty) q
        FROM sale_lines l JOIN sales s ON s.id = l.sale_id
        WHERE s.sold_at >= :start GROUP BY 1, 2
    """), {"tz": env.TZ, "start": now() - timedelta(days=LOOKBACK_DAYS + 28)}).all()
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["d", "p", "q"]).pivot_table(index="d", columns="p", values="q", fill_value=0)
    df.index = pd.to_datetime(df.index)
    df = df.reindex(pd.date_range(df.index.min(), df.index.max()), fill_value=0)
    roll = df.shift(1).rolling(28, min_periods=14).mean()
    recent = df.index >= pd.Timestamp(today() - timedelta(days=LOOKBACK_DAYS))
    products, _ = _names(db)
    out = []
    for d in df.index[recent]:
        for p in df.columns:
            q, mu = float(df.at[d, p]), float(roll.at[d, p]) if not np.isnan(roll.at[d, p]) else 0.0
            if mu > 0 and q >= min_units and q > factor * mu:
                out.append(Finding("sales_spike", f"anomaly:spike:{p}:{d.date()}",
                                   f"Sales of {products.get(int(p), f'product #{p}')} on {d:%d-%m-%Y} were {q:g} units — {q / mu:.1f}× the 28-day average "
                                   f"({mu:.1f}). Check for a bulk order, pricing error or duplicate POS upload.",
                                   "warning", int(p), "sales_day", None, {"qty": q, "rolling_mean": round(mu, 2)}))
    return out


def repeated_corrections(db: Session, min_count: int = 5) -> list[Finding]:
    rows = db.execute(select(StockMovement.user_id, StockMovement.id).where(
        StockMovement.type == "adjustment", StockMovement.reference_type == "adjustment",
        StockMovement.created_at >= _since(), StockMovement.user_id.is_not(None))).all()
    per: dict[int, list[int]] = {}
    for uid, mid in rows:
        per.setdefault(uid, []).append(mid)
    _, users = _names(db)
    return [Finding("repeated_corrections", f"anomaly:rep:{uid}:{today():%G-W%V}",
                    f"{users.get(uid, f'User #{uid}')} made {len(ids)} manual stock corrections in the last {LOOKBACK_DAYS} days. "
                    "Repeated corrections can hide shrinkage — review them.", "warning", None, "user", uid,
                    {"count": len(ids), "movement_ids": ids[-10:]})
            for uid, ids in per.items() if len(ids) >= min_count]


def rule_checks(db: Session) -> list[Finding]:
    return big_adjustments(db) + negative_stock_attempts(db) + cost_changes(db) + sales_spikes(db) + repeated_corrections(db)


# ------------------------------------------------------------------ IsolationForest

TYPES = ["purchase_in", "sale_out", "adjustment", "transfer_in", "transfer_out", "return_out", "write_off"]


def movement_features(db: Session, days: int = 180) -> pd.DataFrame:
    rows = db.execute(select(StockMovement.id, StockMovement.qty, StockMovement.unit_cost, StockMovement.type,
                             StockMovement.user_id, StockMovement.created_at, StockMovement.product_id)
                      .where(StockMovement.created_at >= now() - timedelta(days=days),
                             StockMovement.reference_type != "sales_day")).all()
    df = pd.DataFrame(rows, columns=["id", "qty", "unit_cost", "type", "user_id", "created_at", "product_id"])
    if df.empty:
        return df
    local = pd.to_datetime(df["created_at"], utc=True).dt.tz_convert(TZ)
    df["hour"] = local.dt.hour + local.dt.minute / 60
    df["weekday"] = local.dt.weekday
    df["type_code"] = df["type"].map({t: i for i, t in enumerate(TYPES)}).fillna(len(TYPES))
    df["user_code"] = df["user_id"].fillna(0).astype(int)
    df["abs_qty"] = df["qty"].abs()
    df["value"] = df["abs_qty"] * df["unit_cost"].astype(float)
    df["log_value"] = np.log1p(df["value"])
    df["sign"] = np.sign(df["qty"])
    df["created_at"] = local
    return df


FEATURE_COLS = ["abs_qty", "log_value", "hour", "weekday", "type_code", "user_code", "sign"]


def train_isolation(db: Session) -> ModelRegistry | None:
    df = movement_features(db)
    if len(df) < 50:
        return None
    model = IsolationForest(n_estimators=200, contamination=0.02, random_state=42)
    model.fit(df[FEATURE_COLS].values)
    version = now().strftime("v%Y%m%d-%H%M%S")
    path = env.storage_subdir("models") / f"{MODEL_NAME}_{version}.joblib"
    stats = {c: (float(df[c].mean()), float(df[c].std() or 1.0)) for c in FEATURE_COLS}
    joblib.dump({"model": model, "stats": stats}, path)
    for m in db.scalars(select(ModelRegistry).where(ModelRegistry.name == MODEL_NAME, ModelRegistry.is_active.is_(True))):
        m.is_active = False
    reg = ModelRegistry(name=MODEL_NAME, version=version, trained_at=now(), is_active=True, file_path=str(path),
                        metrics={"rows": len(df), "contamination": 0.02, "features": FEATURE_COLS})
    db.add(reg)
    db.flush()
    return reg


def isolation_findings(db: Session, top: int = 5) -> list[Finding]:
    reg = db.scalar(select(ModelRegistry).where(ModelRegistry.name == MODEL_NAME, ModelRegistry.is_active.is_(True)))
    if not reg or not reg.file_path or not Path(reg.file_path).exists():
        reg = train_isolation(db)
        if reg is None:
            return []
    art = joblib.load(reg.file_path)
    df = movement_features(db, days=LOOKBACK_DAYS)
    if df.empty:
        return []
    scores = art["model"].decision_function(df[FEATURE_COLS].values)
    df["score"] = scores
    flagged = df[df["score"] < 0].sort_values("score").head(top)
    out = []
    for _, r in flagged.iterrows():
        z = {c: (r[c] - art["stats"][c][0]) / art["stats"][c][1] for c in ("abs_qty", "log_value", "hour")}
        reasons = []
        if abs(z["abs_qty"]) > 2:
            reasons.append(f"unusual quantity ({r['qty']:+g})")
        if abs(z["log_value"]) > 2:
            reasons.append(f"high value (₹{r['value']:,.0f})")
        if r["hour"] < 7 or r["hour"] > 22.5:
            reasons.append(f"odd hour ({r['created_at']:%H:%M})")
        why = ", ".join(reasons) or "unusual combination of quantity, time, user and type"
        out.append(Finding("isolation_forest", f"anomaly:if:{int(r['id'])}",
                           f"Unusual {r['type'].replace('_', ' ')} movement on {r['created_at']:%d-%m-%Y %H:%M}: {why}. "
                           f"Anomaly score {r['score']:.3f}.", "warning", int(r["product_id"]), "stock_movement", int(r["id"]),
                           {"score": round(float(r["score"]), 4), "z": {k: round(float(v), 2) for k, v in z.items()},
                            "user_id": int(r["user_code"]) or None, "model_version": reg.version}))
    return out
