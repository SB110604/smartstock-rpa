"""Expiry agent (spec 7.2): days to expiry, projected sell-through, at-risk batches, block expired stock, suggest actions."""

from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentResult
from app.models.ai import Alert
from app.models.inventory import Batch
from app.services import alerts, expiry


class ExpiryAgent(Agent):
    name = "expiry"
    title = "Expiry"
    description = "Flags expired / critical / warning batches using projected sell-through and suggests markdown, return, transfer or write-off."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        rows = expiry.assess(db)
        counts = {"expired": 0, "critical": 0, "warning": 0, "blocked": 0}
        value_at_risk = 0.0
        active_keys = set()
        for r in rows:
            if not r["at_risk"]:
                continue
            bk = r["bucket"]
            if bk == "expired":
                b = db.get(Batch, r["batch_id"])
                if b and not b.is_blocked:
                    b.is_blocked = True  # never sold again (FEFO skips blocked batches)
                    counts["blocked"] += 1
            if bk in ("critical", "warning") and r["markdown_pct"] >= r["suggested_markdown"] > 0:
                continue  # the suggested action was already taken
            counts[bk] += 1
            value_at_risk += r["value"] if bk == "expired" else r["surplus"] * (r["value"] / r["qty"] if r["qty"] else 0)
            type_ = {"expired": "expired", "critical": "expiry_critical", "warning": "expiry_warning"}[bk]
            key = f"expiry:{r['batch_id']}"
            active_keys.add(key)
            when = "expired" if r["days_to_expiry"] <= 0 else f"expires in {r['days_to_expiry']} day(s) ({r['expiry_date']:%d-%m-%Y})"
            alerts.raise_alert(
                db, type_, f"{r['product']} batch {r['batch_no']} at {r['location']}: {r['qty']:g} {r['unit']} {when}. {r['suggestion']}",
                severity="critical" if bk in ("expired", "critical") else "warning", product_id=r["product_id"],
                ref_type="batch", ref_id=r["batch_id"], key=key,
                data={"suggestions": [r["suggestion"]], "actions": r["actions"], "batch_id": r["batch_id"],
                      "projected_sell": r["projected_sell"], "qty": r["qty"], "suggested_markdown": r["suggested_markdown"]})
        # batches that are no longer at risk (sold, written off, marked down) close their alerts
        for a in db.scalars(select(Alert).where(Alert.fingerprint.like("expiry:%"), Alert.status.in_(("open", "acknowledged")))):
            if a.fingerprint not in active_keys:
                alerts.resolve_by_key(db, a.fingerprint, "no longer at risk")
        db.flush()
        return AgentResult(items_processed=len(rows),
                           summary={**counts, "batches_checked": len(rows), "value_at_risk": round(value_at_risk, 2)},
                           data={"assessment": rows})
