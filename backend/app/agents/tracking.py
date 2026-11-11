"""Tracking agent (spec 7.6): predicted delivery dates, late-delivery risk, supplier reminders and escalation, courier."""

from datetime import timedelta

from sqlalchemy import select

from app.agents.base import Agent, AgentContext, AgentResult
from app.core.config import settings as env
from app.core.timeutil import now
from app.models.core import Role, User
from app.models.purchasing import PurchaseOrder
from app.services import alerts, courier, mailer, notify, supplier_scoring
from app.services import settings as settings_svc
from app.workflow.machines import PO


class TrackingAgent(Agent):
    name = "tracking"
    title = "Order tracking"
    description = "Predicts delivery dates from supplier history, flags late deliveries, reminds and escalates unconfirmed POs."

    def run(self, ctx: AgentContext) -> AgentResult:
        db = ctx.db
        stats = supplier_scoring.delivery_stats(db)
        business = settings_svc.get(db, "business")["name"]
        provider = courier.provider()
        t = now()
        late, reminded, escalated, courier_updates = 0, 0, 0, 0
        open_pos = list(db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.in_(PO.OPEN))).unique())
        for po in open_pos:
            st = stats.get(po.supplier_id)
            if st and st.avg_lead_days:
                po.predicted_date = po.order_date + timedelta(days=round(st.avg_lead_days))
            due = po.predicted_date or po.expected_date
            eta_late = bool(po.supplier_eta and po.expected_date and po.supplier_eta > po.expected_date)
            key = f"late_delivery:{po.id}"
            if (due and ctx.day > due) or eta_late:
                late += 1
                days = (ctx.day - po.expected_date).days if po.expected_date and ctx.day > po.expected_date else 0
                reason = (f"supplier ETA {po.supplier_eta:%d-%m-%Y} is after the required date {po.expected_date:%d-%m-%Y}"
                          if eta_late and po.supplier_eta and po.expected_date else
                          f"predicted delivery {due:%d-%m-%Y} has passed" if due else "overdue")
                alerts.raise_alert(db, "late_delivery", f"{po.po_no} from {po.supplier.name} is at risk: {reason}"
                                   + (f" ({days} day(s) past the required date)." if days else "."),
                                   severity="critical" if days > 3 else "warning", ref_type="purchase_order", ref_id=po.id,
                                   key=key, data={"predicted_date": str(due) if due else None, "days_late": days,
                                                  "supplier_mean_lead": round(st.avg_lead_days, 1) if st and st.avg_lead_days else None})
            if po.status == PO.SENT and po.sent_at:
                age_h = (t - po.sent_at).total_seconds() / 3600
                if age_h > 48 and not po.escalated_at:
                    po.escalated_at = t
                    escalated += 1
                    notify.notify_roles(db, [Role.MANAGER], f"{po.po_no} not confirmed for {age_h:.0f} h",
                                        f"{po.supplier.name} has not confirmed. Call them or re-route the order.",
                                        link=f"/orders/{po.id}")
                    alerts.raise_alert(db, "late_delivery", f"{po.po_no}: {po.supplier.name} has not confirmed the order "
                                       f"after {age_h:.0f} hours — escalated to the manager.", severity="warning",
                                       ref_type="purchase_order", ref_id=po.id, key=f"unconfirmed:{po.id}")
                elif age_h > 24 and not po.reminder_sent_at:
                    po.reminder_sent_at = t
                    reminded += 1
                    portal = f"{env.FRONTEND_URL}/portal/orders/{po.id}"
                    if po.supplier.email:
                        mailer.send_email(po.supplier.email, f"Reminder: please confirm purchase order {po.po_no}",
                                          mailer.layout(f"Please confirm {po.po_no}",
                                                        f"<p>We have not received your confirmation for {po.po_no} sent on "
                                                        f"{po.sent_at:%d-%m-%Y %H:%M}. Please confirm and share an ETA.</p>"
                                                        f"{mailer.button(portal, 'Confirm in the portal')}", business))
                    users = list(db.scalars(select(User).where(User.supplier_id == po.supplier_id, User.is_active.is_(True))))
                    if users:
                        notify.notify(db, users, f"Please confirm {po.po_no}", "Confirmation pending for more than 24 hours",
                                      link=f"/portal/orders/{po.id}", channels={"in_app"})
            if po.status == PO.DISPATCHED:
                status = provider.status(po)
                if status and status != po.courier_status:
                    po.courier_status = status
                    courier_updates += 1
        for po in db.scalars(select(PurchaseOrder).where(PurchaseOrder.status.notin_(PO.OPEN),
                                                         PurchaseOrder.updated_at >= t - timedelta(days=30))).unique():
            alerts.resolve_by_key(db, f"late_delivery:{po.id}", "delivered")
            alerts.resolve_by_key(db, f"unconfirmed:{po.id}", "progressed")
        db.flush()
        return AgentResult(items_processed=len(open_pos),
                           summary={"open_pos": len(open_pos), "late_risk": late, "reminders": reminded, "escalations": escalated,
                                    "courier_updates": courier_updates, "courier_provider": provider.name})
