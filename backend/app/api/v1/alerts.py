"""Supplier returns, alerts center and the notification bell."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.core.deps import DB, CurrentUser, require
from app.core.errors import NotFound
from app.core.pagination import PageParams, page_params, paginate
from app.core.timeutil import now
from app.models.ai import Alert, Notification
from app.models.catalog import Product
from app.models.core import StatusHistory, User
from app.models.purchasing import SupplierReturn
from app.services import alerts as alert_svc
from app.workflow import returns

router = APIRouter(tags=["alerts & returns"])
ReturnsMgr = Annotated[User, Depends(require("returns.manage"))]
AlertReader = Annotated[User, Depends(require("alerts.read"))]
AlertWriter = Annotated[User, Depends(require("alerts.write"))]


class ReturnLineIn(BaseModel):
    batch_id: int
    qty: float = Field(gt=0)
    reason: str | None = Field(None, max_length=200)


class ReturnIn(BaseModel):
    supplier_id: int
    location_id: int
    reason: str = Field(min_length=3, max_length=500)
    lines: list[ReturnLineIn] = Field(min_length=1)
    po_id: int | None = None
    submit: bool = True


class TextIn(BaseModel):
    text: str | None = Field(None, max_length=500)


def return_out(db: DB, r: SupplierReturn, history: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r.id, "return_no": r.return_no, "status": r.status, "supplier_id": r.supplier_id, "supplier": r.supplier.name,
        "po_id": r.po_id, "location_id": r.location_id, "reason": r.reason, "subtotal": r.subtotal, "tax": r.tax,
        "total": r.total, "debit_note_no": r.debit_note_no, "credit_note_ref": r.credit_note_ref, "created_at": r.created_at,
        "lines": [{"id": ln.id, "product": ln.product.name, "batch_id": ln.batch_id, "qty": ln.qty,
                   "unit_price": ln.unit_price, "gst_rate": ln.gst_rate, "reason": ln.reason} for ln in r.lines],
    }
    if history:
        out["history"] = [{"from": h.from_status, "to": h.to_status, "note": h.note, "at": h.created_at}
                          for h in db.scalars(select(StatusHistory).where(StatusHistory.entity == "supplier_return",
                                                                          StatusHistory.entity_id == r.id)
                                              .order_by(StatusHistory.id))]
    return out


@router.get("/returns")
def list_returns(user: ReturnsMgr, db: DB, p: Annotated[PageParams, Depends(page_params)],
                 status: str | None = None) -> dict[str, Any]:
    stmt = select(SupplierReturn)
    if status:
        stmt = stmt.where(SupplierReturn.status == status)
    page = paginate(db, stmt.order_by(SupplierReturn.id.desc()), p)
    page["items"] = [return_out(db, r) for r in page["items"]]
    return page


@router.post("/returns", status_code=201)
def create_return(body: ReturnIn, user: ReturnsMgr, db: DB) -> dict[str, Any]:
    r = returns.create(db, supplier_id=body.supplier_id, location_id=body.location_id, reason=body.reason, user=user,
                       lines=[ln.model_dump() for ln in body.lines], po_id=body.po_id)
    if body.submit:
        returns.submit(db, r, user)
    db.commit()
    return return_out(db, r, history=True)


@router.get("/returns/{return_id}")
def get_return(return_id: int, user: ReturnsMgr, db: DB) -> dict[str, Any]:
    return return_out(db, returns.get(db, return_id), history=True)


@router.post("/returns/{return_id}/{action}")
def return_action(return_id: int, action: str, body: TextIn, user: ReturnsMgr, db: DB) -> dict[str, Any]:
    r = returns.get(db, return_id)
    handlers = {
        "submit": lambda: returns.submit(db, r, user),
        "approve": lambda: returns.approve(db, r, user),
        "reject": lambda: returns.reject(db, r, user, body.text),
        "cancel": lambda: returns.cancel(db, r, user, body.text),
        "dispatch": lambda: returns.dispatch(db, r, user),
        "credit": lambda: returns.credit(db, r, user, body.text or ""),
    }
    if action not in handlers:
        raise NotFound("Unknown action")
    handlers[action]()
    return return_out(db, r, history=True)


@router.get("/returns/{return_id}/pdf")
def return_pdf(return_id: int, user: ReturnsMgr, db: DB) -> Response:
    r = returns.get(db, return_id)
    data = returns.pdf(db, r)
    db.commit()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{r.debit_note_no or r.return_no}.pdf"'})


# ---------------------------------------------------------------- alerts

def alert_out(a: Alert, names: dict[int, str]) -> dict[str, Any]:
    return {"id": a.id, "type": a.type, "severity": a.severity, "product_id": a.product_id,
            "product": names.get(a.product_id or 0), "ref_type": a.ref_type, "ref_id": a.ref_id, "message": a.message,
            "data": a.data_json, "status": a.status, "resolution": a.resolution, "created_at": a.created_at,
            "resolved_at": a.resolved_at}


@router.get("/alerts")
def list_alerts(user: AlertReader, db: DB, p: Annotated[PageParams, Depends(page_params)], type: str | None = None,
                severity: str | None = None, status: str | None = "open,acknowledged",
                product_id: int | None = None) -> dict[str, Any]:
    stmt = select(Alert)
    if type:
        stmt = stmt.where(Alert.type.in_(type.split(",")))
    if severity:
        stmt = stmt.where(Alert.severity.in_(severity.split(",")))
    if status:
        stmt = stmt.where(Alert.status.in_(status.split(",")))
    if product_id:
        stmt = stmt.where(Alert.product_id == product_id)
    sev_order = func.array_position(["critical", "warning", "info"], Alert.severity)
    page = paginate(db, stmt.order_by(sev_order, Alert.created_at.desc()), p)
    pids = {a.product_id for a in page["items"] if a.product_id}
    names = dict(db.execute(select(Product.id, Product.name).where(Product.id.in_(pids))).all()) if pids else {}
    page["items"] = [alert_out(a, names) for a in page["items"]]
    return page


@router.get("/alerts/summary")
def alert_summary(user: AlertReader, db: DB) -> dict[str, Any]:
    rows = db.execute(select(Alert.type, Alert.severity, func.count()).where(Alert.status.in_(("open", "acknowledged")))
                      .group_by(Alert.type, Alert.severity)).all()
    by_type: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for t, s, n in rows:
        by_type[t] = by_type.get(t, 0) + n
        by_sev[s] = by_sev.get(s, 0) + n
    return {"open": sum(by_type.values()), "by_type": by_type, "by_severity": by_sev}


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, user: AlertWriter, db: DB) -> dict[str, Any]:
    return alert_out(alert_svc.acknowledge(db, alert_svc.get(db, alert_id), user), {})


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: int, body: TextIn, user: AlertWriter, db: DB) -> dict[str, Any]:
    return alert_out(alert_svc.resolve(db, alert_svc.get(db, alert_id), user, body.text), {})


# ---------------------------------------------------------------- notifications (every logged-in user, own rows only)

@router.get("/notifications")
def notifications(user: CurrentUser, db: DB, p: Annotated[PageParams, Depends(page_params)],
                  unread: bool = False) -> dict[str, Any]:
    stmt = select(Notification).where(Notification.user_id == user.id, Notification.channel == "in_app")
    if unread:
        stmt = stmt.where(Notification.read_at.is_(None))
    return paginate(db, stmt.order_by(Notification.id.desc()), p,
                    lambda n: {"id": n.id, "title": n.title, "body": n.body, "link": n.link, "alert_id": n.alert_id,
                               "created_at": n.created_at, "read_at": n.read_at})


@router.get("/notifications/unread-count")
def unread_count(user: CurrentUser, db: DB) -> dict[str, int]:
    n = db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.channel == "in_app", Notification.read_at.is_(None)))
    return {"unread": n or 0}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int, user: CurrentUser, db: DB) -> dict[str, str]:
    n = db.get(Notification, notification_id)
    if not n or n.user_id != user.id:
        raise NotFound("Notification not found")
    n.read_at = n.read_at or now()
    db.commit()
    return {"detail": "ok"}


@router.post("/notifications/read-all")
def mark_all(user: CurrentUser, db: DB) -> dict[str, int]:
    res = db.execute(update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
                     .values(read_at=now()))
    db.commit()
    return {"updated": res.rowcount or 0}  # type: ignore[attr-defined]
