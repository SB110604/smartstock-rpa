"""Auto-order agent (spec 7.5): turn recommendations into purchase requests, route them for approval, group POs."""

from sqlalchemy import select

from app import llm
from app.agents.base import Agent, AgentContext, AgentResult
from app.models.purchasing import PoLine, PurchaseOrder, PurchaseRequest
from app.workflow import purchasing
from app.workflow.machines import PO, PR


class AutoOrderAgent(Agent):
    name = "auto_order"
    title = "Auto-order"
    description = "Creates purchase requests from recommendations, routes them to approval and groups approved ones into POs."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        src = ctx.results.get("supplier") or ctx.results.get("decision")
        recs = src.data.get("recommendations", []) if src else []
        open_prs = set(db.execute(select(PurchaseRequest.product_id, PurchaseRequest.location_id)
                                  .where(PurchaseRequest.status.in_(PR.OPEN))).tuples())
        open_prs |= set(db.execute(select(PoLine.product_id, PurchaseOrder.location_id)
                                   .join(PurchaseOrder, PurchaseOrder.id == PoLine.po_id)
                                   .where(PurchaseOrder.status.in_(PO.OPEN))).tuples())
        created, skipped_open, skipped_priority, auto, pending = [], 0, 0, 0, 0
        for r in sorted(recs, key=lambda x: (not x["out_of_stock"], -x["priority"])):
            key = (r["product_id"], r["location_id"])
            if key in open_prs:
                skipped_open += 1
                continue
            if r["priority"] < 0 and not r["out_of_stock"]:
                skipped_priority += 1  # repeatedly rejected suggestions wait until the item actually runs out
                continue
            text = llm.polish(r["reason_text"], context=f"Product #{r['product_id']}")
            pr = purchasing.create_request(db, product_id=r["product_id"], location_id=r["location_id"], qty=r["qty"],
                                           supplier_id=r.get("supplier_id"), user=None, created_by="agent",
                                           reason_text=text, reason_json=r["reason_json"])
            open_prs.add(key)
            created.append(pr.id)
            if pr.status == PR.APPROVED:
                auto += 1
            else:
                pending += 1
        pos = purchasing.create_purchase_orders(db, actor=None) if auto else []
        db.flush()
        return AgentResult(items_processed=len(recs),
                           summary={"recommendations": len(recs), "requests_created": len(created), "auto_approved": auto,
                                    "pending_approval": pending, "skipped_open_request": skipped_open,
                                    "skipped_low_priority": skipped_priority, "purchase_orders": [p.po_no for p in pos],
                                    "llm": llm.status()["provider"] if llm.get_provider() else "template"},
                           data={"request_ids": created})
