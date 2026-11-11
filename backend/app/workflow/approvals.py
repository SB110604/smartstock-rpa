"""Approval engine (spec 8.1): routing by approval rules, multi-level decisions, one-click tokens, SLA."""

from datetime import timedelta
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.errors import Forbidden, NotFound, ValidationFailed
from app.core.security import hash_token, new_token
from app.core.timeutil import now
from app.models.catalog import SupplierProduct
from app.models.core import Role, User
from app.models.purchasing import Approval, ApprovalRule, ApprovalToken, PurchaseRequest
from app.services import alerts, audit, learning, mailer, notify
from app.services import settings as settings_svc
from app.services.pdfbase import inr
from app.workflow.engine import transition
from app.workflow.machines import PR, purchase_request

TOKEN_HOURS = 48


# ------------------------------------------------------------------ routing

def rules(db: Session) -> list[ApprovalRule]:
    return list(db.scalars(select(ApprovalRule).order_by(ApprovalRule.min_amount)))


def route(db: Session, amount: float) -> list[str]:
    """Approver roles in order for an estimated total. Empty list = auto-approve.
    A rule matches when min < amount ≤ max (the first rule also matches 0). Admin-level needs manager then admin."""
    for i, r in enumerate(rules(db)):
        above_min = amount > r.min_amount or (i == 0 and amount >= r.min_amount)
        if above_min and (r.max_amount is None or amount <= r.max_amount):
            if r.auto_approve or not r.approver_role:
                return []
            return [Role.MANAGER, Role.ADMIN] if r.approver_role == Role.ADMIN else [r.approver_role]
    return [Role.MANAGER, Role.ADMIN]  # no rule covers it → strictest path


def replace_rules(db: Session, items: list[dict[str, Any]], user: User) -> list[ApprovalRule]:
    items = sorted(items, key=lambda r: float(r["min_amount"]))
    if not items or float(items[0]["min_amount"]) != 0:
        raise ValidationFailed("The first rule must start at ₹0")
    for a, b in pairwise(items):
        if a.get("max_amount") is None or float(a["max_amount"]) != float(b["min_amount"]):
            raise ValidationFailed("Rules must be contiguous: each rule starts where the previous one ends")
    if items[-1].get("max_amount") is not None:
        raise ValidationFailed("The last rule must have no upper limit")
    for r in items:
        if not r.get("auto_approve") and r.get("approver_role") not in (Role.MANAGER, Role.ADMIN):
            raise ValidationFailed("Each rule needs auto-approve or an approver role (manager/admin)")
    before = [{"min": r.min_amount, "max": r.max_amount, "role": r.approver_role, "auto": r.auto_approve} for r in rules(db)]
    for r in rules(db):
        db.delete(r)
    db.flush()
    for r in items:
        db.add(ApprovalRule(min_amount=float(r["min_amount"]),
                            max_amount=None if r.get("max_amount") is None else float(r["max_amount"]),
                            approver_role=None if r.get("auto_approve") else r["approver_role"],
                            auto_approve=bool(r.get("auto_approve"))))
    audit.record(db, user, "update", "approval_rules", None, {"rules": before}, {"rules": items})
    db.commit()
    return rules(db)


# ------------------------------------------------------------------ tokens & messages

def _issue_tokens(db: Session, approval: Approval, user: User) -> dict[str, str]:
    """Single-use approve/reject tokens for one approver, for both email and Telegram links."""
    out: dict[str, str] = {}
    exp = now() + timedelta(hours=TOKEN_HOURS)
    for channel in ("em", "tg"):
        for action in ("approve", "reject"):
            raw, _ = new_token()
            raw = f"{channel}_{raw}"
            db.add(ApprovalToken(token_hash=hash_token(raw), approval_id=approval.id, user_id=user.id, action=action,
                                 expires_at=exp))
            out[f"{channel}_{action}"] = raw
    return out


def summary(pr: PurchaseRequest) -> str:
    sup = pr.final_supplier or pr.suggested_supplier
    qty = pr.final_qty if pr.final_qty is not None else pr.suggested_qty
    return f"{pr.product.name}: {qty:g} {pr.product.unit} from {sup.name if sup else '—'} · est. {inr(pr.est_total)}"


def _ask(db: Session, pr: PurchaseRequest, approval: Approval, users: list[User], prefix: str = "Approval needed") -> None:
    business = settings_svc.get(db, "business")["name"]
    for u in users:
        tok = _issue_tokens(db, approval, u)
        base = f"{env.FRONTEND_URL}/approval?token="
        reason = pr.reason_text or ""
        html = mailer.layout(
            f"{prefix}: purchase request #{pr.id}",
            f"<p>{summary(pr)}</p><p style='color:#475569'>{reason}</p>"
            f"<p>Level {approval.level} ({approval.approver_role}).</p>"
            f"{mailer.button(base + tok['em_approve'], 'Approve')}{mailer.button(base + tok['em_reject'], 'Reject', '#e11d48')}"
            f"<p style='font-size:12px;color:#64748b'>Links are single-use and expire in {TOKEN_HOURS} hours. "
            f"Or review it in the app: {env.FRONTEND_URL}/approvals?pr={pr.id}</p>",
            business,
        )
        tg = (f"<b>{prefix}</b> — PR #{pr.id}\n{summary(pr)}\n\n✅ Approve: {base}{tok['tg_approve']}\n"
              f"❌ Reject: {base}{tok['tg_reject']}")
        notify.notify(db, [u], f"{prefix}: PR #{pr.id}", summary(pr), link=f"/approvals?pr={pr.id}", email_html=html,
                      telegram_text=tg)


def _approvers(db: Session, role: str) -> list[User]:
    return notify.users_with_roles(db, [role])


# ------------------------------------------------------------------ lifecycle

def submit(db: Session, pr: PurchaseRequest, actor: User | None, actor_type: str | None = None) -> PurchaseRequest:
    levels = route(db, pr.est_total)
    transition(db, purchase_request, pr, PR.PENDING, actor=actor, actor_type=actor_type,
               note=f"Routed to {' → '.join(levels) if levels else 'auto-approval'}")
    pr.submitted_at = now()
    pr.required_levels = len(levels)
    if not levels:
        pr.approvals.append(Approval(level=1, approver_role="system", decision="approved", via="auto", decided_at=now(),
                                     comment="Auto-approved by rule (within auto-approve limit)"))
        db.flush()
        transition(db, purchase_request, pr, PR.APPROVED, actor=None, actor_type="system", note="Auto-approved")
        return pr
    for i, role in enumerate(levels, start=1):
        pr.approvals.append(Approval(level=i, approver_role=role))
    db.flush()
    _ask(db, pr, pr.approvals[0], _approvers(db, levels[0]))
    return pr


def current_approval(pr: PurchaseRequest) -> Approval | None:
    return next((a for a in sorted(pr.approvals, key=lambda a: a.level) if a.decision == "pending"), None)


def _can_act(user: User, approval: Approval) -> bool:
    return user.role == Role.ADMIN or user.role == approval.approver_role


def decide(
    db: Session,
    pr: PurchaseRequest,
    user: User,
    action: str,
    *,
    comment: str | None = None,
    final_qty: float | None = None,
    final_supplier_id: int | None = None,
    via: str = "web",
    create_po: bool = True,
) -> PurchaseRequest:
    if pr.status != PR.PENDING:
        # route through the state machine so the caller gets the standard 409
        transition(db, purchase_request, pr, PR.APPROVED if action == "approve" else PR.REJECTED, actor=user)
    approval = current_approval(pr)
    if approval is None:
        raise ValidationFailed("No pending approval level")
    if not _can_act(user, approval):
        raise Forbidden(f"This request needs {approval.approver_role} approval at level {approval.level}")
    approval.approver_id, approval.decided_at, approval.via, approval.comment = user.id, now(), via, comment
    if action == "reject":
        if not comment or not comment.strip():
            raise ValidationFailed("A reason is required to reject")
        approval.decision = "rejected"
        for a in pr.approvals:
            if a.decision == "pending":
                a.decision = "skipped"
        pr.rejection_reason = comment.strip()
        transition(db, purchase_request, pr, PR.REJECTED, actor=user, note=comment)
        learning.record_feedback(db, pr, "rejected", comment, user)
        _close_tokens(db, pr)
        if pr.created_by_user_id and pr.created_by_user_id != user.id:
            creator = db.get(User, pr.created_by_user_id)
            if creator:
                notify.notify(db, [creator], f"PR #{pr.id} rejected", f"{summary(pr)} — {comment}",
                              link=f"/approvals?pr={pr.id}", channels={"in_app"})
        return pr
    if action != "approve":
        raise ValidationFailed("action must be approve or reject")
    edited = False
    if final_qty is not None:
        if final_qty <= 0:
            raise ValidationFailed("Quantity must be greater than zero")
        edited = edited or abs(final_qty - pr.suggested_qty) > 1e-9
        pr.final_qty = final_qty
    if final_supplier_id is not None and final_supplier_id != (pr.final_supplier_id or pr.suggested_supplier_id):
        sp = db.scalar(select(SupplierProduct).where(SupplierProduct.supplier_id == final_supplier_id,
                                                     SupplierProduct.product_id == pr.product_id))
        if not sp:
            raise ValidationFailed("That supplier has no price for this product")
        pr.final_supplier_id = final_supplier_id
        pr.est_unit_price = sp.unit_price
        edited = True
    pr.final_qty = pr.final_qty if pr.final_qty is not None else pr.suggested_qty
    pr.final_supplier_id = pr.final_supplier_id or pr.suggested_supplier_id
    pr.est_total = round(pr.final_qty * pr.est_unit_price, 2)
    approval.decision = "approved"
    nxt = current_approval(pr)
    db.flush()
    if nxt:
        db.refresh(pr, attribute_names=["final_supplier"])
        _ask(db, pr, nxt, _approvers(db, nxt.approver_role), prefix=f"Level {nxt.level} approval needed")
        audit.record(db, user, "approve_level", "purchase_request", pr.id, None,
                     {"level": approval.level, "next": nxt.approver_role, "via": via})
        return pr
    transition(db, purchase_request, pr, PR.APPROVED, actor=user, note=comment or ("Edited and approved" if edited else None))
    learning.record_feedback(db, pr, "edited" if edited else "approved", comment, user)
    _close_tokens(db, pr)
    if create_po:
        from app.workflow import purchasing

        purchasing.create_purchase_orders(db, actor=user, pr_ids=[pr.id])
    return pr


def _close_tokens(db: Session, pr: PurchaseRequest) -> None:
    ids = [a.id for a in pr.approvals]
    for t in db.scalars(select(ApprovalToken).where(ApprovalToken.approval_id.in_(ids), ApprovalToken.used_at.is_(None))):
        t.used_at = now()


def bulk_approve(db: Session, pr_ids: list[int], user: User) -> dict[str, Any]:
    done, failed = [], []
    for pid in pr_ids:
        pr = db.get(PurchaseRequest, pid)
        if not pr:
            failed.append({"id": pid, "error": "not found"})
            continue
        sp = db.begin_nested()
        try:
            decide(db, pr, user, "approve", via="web", create_po=False)
            sp.commit()
            done.append(pid)
        except Exception as exc:  # report per-request problems, keep approving the rest
            sp.rollback()
            failed.append({"id": pid, "error": getattr(exc, "detail", str(exc))})
    from app.workflow import purchasing

    pos = purchasing.create_purchase_orders(db, actor=user, pr_ids=done) if done else []
    db.commit()
    return {"approved": done, "failed": failed, "purchase_orders": [p.po_no for p in pos]}


# ------------------------------------------------------------------ one-click tokens

def _token(db: Session, raw: str) -> ApprovalToken:
    tok = db.scalar(select(ApprovalToken).where(ApprovalToken.token_hash == hash_token(raw)))
    if not tok:
        raise NotFound("This approval link is not valid", code="token_invalid")
    if tok.used_at:
        raise ValidationFailed("This approval link was already used", code="token_used")
    if tok.expires_at < now():
        raise ValidationFailed("This approval link has expired", code="token_expired")
    return tok


def token_info(db: Session, raw: str) -> dict[str, Any]:
    tok = _token(db, raw)
    approval = db.get(Approval, tok.approval_id)
    pr = db.get(PurchaseRequest, approval.purchase_request_id) if approval else None
    if not approval or not pr or approval.decision != "pending":
        raise ValidationFailed("This request has already been decided", code="token_used")
    user = db.get(User, tok.user_id) if tok.user_id else None
    return {"action": tok.action, "level": approval.level, "approver": user.name if user else None,
            "request": {"id": pr.id, "product": pr.product.name, "qty": pr.final_qty or pr.suggested_qty,
                        "unit": pr.product.unit, "supplier": (pr.final_supplier or pr.suggested_supplier).name
                        if (pr.final_supplier or pr.suggested_supplier) else None, "est_total": pr.est_total,
                        "reason_text": pr.reason_text, "status": pr.status},
            "expires_at": tok.expires_at}


def use_token(db: Session, raw: str, reason: str | None) -> PurchaseRequest:
    tok = _token(db, raw)
    approval = db.get(Approval, tok.approval_id)
    user = db.get(User, tok.user_id) if tok.user_id else None
    if not approval or not user or not user.is_active:
        raise NotFound("This approval link is not valid", code="token_invalid")
    pr = db.get(PurchaseRequest, approval.purchase_request_id)
    assert pr is not None
    if approval.decision != "pending":
        raise ValidationFailed("This request has already been decided", code="token_used")
    tok.used_at = now()
    via = "telegram" if raw.startswith("tg_") else "email_link"
    decide(db, pr, user, tok.action, comment=reason, via=via)
    db.commit()
    return pr


# ------------------------------------------------------------------ SLA

def check_sla(db: Session) -> dict[str, int]:
    """Reminder after approval_sla_hours, escalation to the next role after 2× (Celery Beat, every 30 min)."""
    sla = float(settings_svc.get(db, "approval_sla_hours"))
    t = now()
    reminded = escalated = 0
    pending = db.scalars(select(PurchaseRequest).where(PurchaseRequest.status == PR.PENDING))
    for pr in pending.unique():
        ap = current_approval(pr)
        if not ap:
            continue
        prev = [a for a in pr.approvals if a.level < ap.level and a.decided_at]
        since = max((a.decided_at for a in prev), default=pr.submitted_at or ap.created_at)
        age_h = (t - since).total_seconds() / 3600
        if age_h > 2 * sla and not ap.escalated_at:
            ap.escalated_at = t
            target = Role.ADMIN
            _ask(db, pr, ap, _approvers(db, target), prefix="Escalated approval")
            alerts.raise_alert(db, "approval_pending", f"PR #{pr.id} has waited {age_h:.0f} h for {ap.approver_role} "
                               f"approval and was escalated to admin. {summary(pr)}", severity="critical",
                               ref_type="purchase_request", ref_id=pr.id, product_id=pr.product_id,
                               key=f"approval_pending:{pr.id}")
            escalated += 1
        elif age_h > sla and not ap.reminded_at:
            ap.reminded_at = t
            _ask(db, pr, ap, _approvers(db, ap.approver_role), prefix="Reminder")
            alerts.raise_alert(db, "approval_pending", f"PR #{pr.id} is waiting {age_h:.0f} h for "
                               f"{ap.approver_role} approval (SLA {sla:g} h). {summary(pr)}",
                               ref_type="purchase_request", ref_id=pr.id, product_id=pr.product_id,
                               key=f"approval_pending:{pr.id}")
            reminded += 1
    db.commit()
    return {"reminded": reminded, "escalated": escalated}
