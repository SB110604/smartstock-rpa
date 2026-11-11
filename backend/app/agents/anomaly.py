"""Anomaly agent (spec 7.7): rule checks + IsolationForest on movements; every finding becomes an explained alert."""

from app.agents.base import Agent, AgentContext, AgentResult
from app.ml import anomaly
from app.services import alerts


class AnomalyAgent(Agent):
    name = "anomaly"
    title = "Anomaly detection"
    description = "Unusual adjustments, negative-stock attempts, cost jumps, sales spikes, repeated corrections and IsolationForest outliers."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        trained = None
        if ctx.triggered_by in ("weekly", "seed"):
            reg = anomaly.train_isolation(db)
            trained = reg.version if reg else None
        findings = anomaly.rule_checks(db) + anomaly.isolation_findings(db)
        new = 0
        by_rule: dict[str, int] = {}
        for f in findings:
            _, created = alerts.raise_alert(db, "anomaly", f.message, severity=f.severity, product_id=f.product_id,
                                            ref_type=f.ref_type, ref_id=f.ref_id, key=f.key,
                                            data={**f.data, "rule": f.rule})
            new += int(created)
            by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
        db.flush()
        return AgentResult(items_processed=len(findings),
                           summary={"findings": len(findings), "new_alerts": new, "by_rule": by_rule, "model_trained": trained})
