"""Purchase requests, approvals (incl. one-click links) and approval rules."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.v1.suppliers import latest_scores
from app.core.deps import DB, CurrentUser, require
from app.core.errors import NotFound
from app.core.pagination import PageParams, apply_sort, page_params, paginate
from app.models.catalog import Product, SupplierProduct
from app.models.core import StatusHistory, User
from app.models.purchasing import PurchaseRequest
from app.services import stock
from app.workflow import approvals, purchasing

router = APIRouter(tags=["purchasing"])
Reader = Annotated[User, Depends(require("purchasing.read"))]
Writer = Annotated[User, Depends(require("purchasing.write"))]
Approver = Annotated[User, Depends(require("purchasing.approve"))]
Admin = Annotated[User, Depends(require("settings.manage"))]


class PRIn(BaseModel):
    product_id: int
    location_id: int
    qty: float = Field(gt=0)
    supplier_id: int | None = None
    note: str | None = Field(None, max_length=1000)
    submit: bool = True


class DecideIn(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    comment: str | None = Field(None, max_length=1000)
    final_qty: float | None = Field(None, gt=0)
    final_supplier_id: int | None = None


class BulkIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class ReasonIn(BaseModel):
    reason: str | None = Field(None, max_length=1000)


class RuleIn(BaseModel):
    min_amount: float = Field(ge=0)
    max_amount: float | None = Field(None, gt=0)
    approver_role: str | None = Field(None, pattern="^(manager|admin)$")
    auto_approve: bool = False


def pr_out(pr: PurchaseRequest) -> dict[str, Any]:
    cur = approvals.current_approval(pr)
    sup = pr.final_supplier or pr.suggested_supplier
    return {
        "id": pr.id, "status": pr.status, "product_id": pr.product_id, "product": pr.product.name, "sku": pr.product.sku,
        "unit": pr.product.unit, "location_id": pr.location_id, "location": pr.location.name,
        "suggested_qty": pr.suggested_qty, "final_qty": pr.final_qty,
        "suggested_supplier_id": pr.suggested_supplier_id,
        "suggested_supplier": pr.suggested_supplier.name if pr.suggested_supplier else None,
        "final_supplier_id": pr.final_supplier_id, "supplier": sup.name if sup else None,
        "est_unit_price": pr.est_unit_price, "est_total": pr.est_total, "reason_text": pr.reason_text,
        "created_by": pr.created_by, "created_at": pr.created_at, "submitted_at": pr.submitted_at,
        "required_levels": pr.required_levels, "rejection_reason": pr.rejection_reason, "po_id": pr.po_id,
        "current_level": cur.level if cur else None, "current_role": cur.approver_role if cur else None,
        "escalated": bool(cur and cur.escalated_at),
        "approvals": [{"level": a.level, "role": a.approver_role, "decision": a.decision, "via": a.via,
                       "approver_id": a.approver_id, "comment": a.comment, "decided_at": a.decided_at}
                      for a in sorted(pr.approvals, key=lambda a: a.level)],
    }


def get_pr(db: DB, pr_id: int) -> PurchaseRequest:
    pr = db.get(PurchaseRequest, pr_id)
    if not pr:
        raise NotFound("Purchase request not found")
    return pr


@router.get("/purchase-requests")
def list_requests(user: Reader, db: DB, p: Annotated[PageParams, Depends(page_params)], status: str | None = None,
                  q: str | None = None, created_by: str | None = None, mine: bool = False) -> dict[str, Any]:
    stmt = select(PurchaseRequest).join(Product, Product.id == PurchaseRequest.product_id)
    if status:
        stmt = stmt.where(PurchaseRequest.status.in_(status.split(",")))
    if q:
        stmt = stmt.where(or_(Product.name.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%")))
    if created_by:
        stmt = stmt.where(PurchaseRequest.created_by == created_by)
    if mine:  # pending at a level this user can act on
        rows = [pr for pr in db.scalars(stmt.where(PurchaseRequest.status == "PENDING_APPROVAL")
                                        .order_by(PurchaseRequest.created_at)).unique()
                if (cur := approvals.current_approval(pr)) and (user.role == "admin" or cur.approver_role == user.role)]
        start = (p.page - 1) * p.page_size
        return {"items": [pr_out(r) for r in rows[start:start + p.page_size]], "total": len(rows), "page": p.page,
                "page_size": p.page_size}
    stmt = apply_sort(stmt, p.sort, {"created_at": PurchaseRequest.created_at, "est_total": PurchaseRequest.est_total,
                                     "product": Product.name}, PurchaseRequest.created_at.desc())
    return paginate(db, stmt, p, pr_out)


@router.get("/purchase-requests/{pr_id}")
def request_detail(pr_id: int, user: Reader, db: DB) -> dict[str, Any]:
    pr = get_pr(db, pr_id)
    history = db.scalars(select(StatusHistory).where(StatusHistory.entity == "purchase_request",
                                                     StatusHistory.entity_id == pr.id).order_by(StatusHistory.id))
    scores = latest_scores(db)
    options = db.scalars(select(SupplierProduct).where(SupplierProduct.product_id == pr.product_id)
                         .order_by(SupplierProduct.unit_price)).unique()
    return {
        **pr_out(pr),
        "reason_json": pr.reason_json,
        "position": stock.position(db, pr.product_id, pr.location_id),
        "pack_size": pr.product.pack_size,
        "history": [{"from": h.from_status, "to": h.to_status, "note": h.note, "actor_type": h.actor_type,
                     "at": h.created_at} for h in history],
        "supplier_options": [{"supplier_id": sp.supplier_id, "name": sp.supplier.name, "unit_price": sp.unit_price,
                              "lead_time_days": sp.lead_time_days,
                              "score": round(scores[sp.supplier_id].total_score, 1) if sp.supplier_id in scores else None}
                             for sp in options],
    }


@router.post("/purchase-requests", status_code=201)
def create_request(body: PRIn, user: Writer, db: DB) -> dict[str, Any]:
    pr = purchasing.create_request(db, product_id=body.product_id, location_id=body.location_id, qty=body.qty,
                                   supplier_id=body.supplier_id, user=user, created_by="user",
                                   reason_text=body.note or "Created manually", submit=body.submit)
    if pr.status == "APPROVED":
        purchasing.create_purchase_orders(db, actor=user, pr_ids=[pr.id])
    db.commit()
    return pr_out(pr)


@router.post("/purchase-requests/{pr_id}/submit")
def submit_request(pr_id: int, user: Writer, db: DB) -> dict[str, Any]:
    pr = get_pr(db, pr_id)
    approvals.submit(db, pr, user)
    if pr.status == "APPROVED":
        purchasing.create_purchase_orders(db, actor=user, pr_ids=[pr.id])
    db.commit()
    return pr_out(pr)


@router.post("/purchase-requests/{pr_id}/decide")
def decide(pr_id: int, body: DecideIn, user: Approver, db: DB) -> dict[str, Any]:
    pr = get_pr(db, pr_id)
    approvals.decide(db, pr, user, body.action, comment=body.comment, final_qty=body.final_qty,
                     final_supplier_id=body.final_supplier_id, via="web")
    db.commit()
    return pr_out(pr)


@router.post("/purchase-requests/bulk-approve")
def bulk_approve(body: BulkIn, user: Approver, db: DB) -> dict[str, Any]:
    return approvals.bulk_approve(db, body.ids, user)


@router.post("/purchase-requests/{pr_id}/cancel")
def cancel_request(pr_id: int, body: ReasonIn, user: Writer, db: DB) -> dict[str, Any]:
    return pr_out(purchasing.cancel_request(db, get_pr(db, pr_id), user, body.reason))


@router.get("/approvals/summary")
def approvals_summary(user: CurrentUser, db: DB) -> dict[str, int]:
    pending = list(db.scalars(select(PurchaseRequest).where(PurchaseRequest.status == "PENDING_APPROVAL")).unique())
    mine = [pr for pr in pending if (c := approvals.current_approval(pr)) and (user.role == "admin" or c.approver_role == user.role)]
    return {"pending": len(pending), "mine": len(mine)}


# ---------------------------------------------------------------- approval rules

@router.get("/approval-rules")
def get_rules(user: Reader, db: DB) -> list[dict[str, Any]]:
    return [{"id": r.id, "min_amount": r.min_amount, "max_amount": r.max_amount, "approver_role": r.approver_role,
             "auto_approve": r.auto_approve} for r in approvals.rules(db)]


@router.put("/approval-rules")
def put_rules(body: list[RuleIn], user: Admin, db: DB) -> list[dict[str, Any]]:
    approvals.replace_rules(db, [r.model_dump() for r in body], user)
    return get_rules(user, db)


@router.get("/approval-rules/route")
def preview_route(amount: float, user: Reader, db: DB) -> dict[str, Any]:
    return {"amount": amount, "levels": approvals.route(db, amount)}


# ---------------------------------------------------------------- one-click links (no login: the token is the auth)

@router.get("/approvals/token/{token}")
def token_info(token: str, db: DB) -> dict[str, Any]:
    return approvals.token_info(db, token)


@router.post("/approvals/token/{token}")
def use_token(token: str, body: ReasonIn, db: DB) -> dict[str, Any]:
    pr = approvals.use_token(db, token, body.reason)
    return {"id": pr.id, "status": pr.status, "detail": f"Purchase request #{pr.id} is now {pr.status.replace('_', ' ').lower()}"}
