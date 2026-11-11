"""Continuous learning from approver decisions (spec 7.9)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai import Feedback
from app.models.catalog import Product
from app.models.core import User
from app.models.purchasing import PurchaseRequest
from app.services import alerts

ALPHA = 0.3
CLAMP = (0.5, 1.5)
REJECT_STREAK = 3


def record_feedback(db: Session, pr: PurchaseRequest, decision: str, reason: str | None, user: User | None) -> Feedback:
    """Every approval decision writes a feedback row; 3 rejections in a row lower the product's priority."""
    fb = Feedback(purchase_request_id=pr.id, product_id=pr.product_id, suggested_qty=pr.suggested_qty,
                  final_qty=pr.final_qty if decision != "rejected" else None, decision=decision, reason=reason,
                  user_id=user.id if user else None)
    db.add(fb)
    db.flush()
    if decision == "rejected" and pr.created_by == "agent":
        last = list(db.scalars(select(Feedback.decision).where(Feedback.product_id == pr.product_id)
                               .order_by(Feedback.id.desc()).limit(REJECT_STREAK)))
        if len(last) == REJECT_STREAK and all(d == "rejected" for d in last):
            product = db.get(Product, pr.product_id)
            if product:
                product.priority -= 1
                alerts.raise_alert(
                    db, "suggestion_rejected",
                    f"AI suggestions for {product.name} were rejected {REJECT_STREAK} times in a row; "
                    "its reorder priority was lowered. Review its reorder settings.",
                    severity="info", product_id=product.id, data={"priority": product.priority, "last_reason": reason},
                )
    return fb


def correction_factor(db: Session, product_id: int) -> float:
    """EMA (α = 0.3) of final_qty / suggested_qty over approved/edited agent suggestions, clamped to [0.5, 1.5]."""
    rows = db.execute(
        select(Feedback.suggested_qty, Feedback.final_qty)
        .join(PurchaseRequest, PurchaseRequest.id == Feedback.purchase_request_id)
        .where(Feedback.product_id == product_id, Feedback.decision.in_(("approved", "edited")),
               Feedback.final_qty.is_not(None), Feedback.suggested_qty > 0, PurchaseRequest.created_by == "agent")
        .order_by(Feedback.id)
    ).all()
    factor = 1.0
    for suggested, final in rows:
        factor = ALPHA * (final / suggested) + (1 - ALPHA) * factor
    return round(min(max(factor, CLAMP[0]), CLAMP[1]), 4)
