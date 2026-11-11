"""Notification hooks for workflow transitions that have no richer, explicit message elsewhere."""

from typing import Any

from sqlalchemy.orm import Session

from app.models.core import Role, User
from app.services import notify
from app.workflow.machines import RET, TR, stock_transfer, supplier_return


@stock_transfer.on_transition
def _transfer(db: Session, tr: Any, frm: str, to: str, actor: User | None, note: str | None) -> None:
    roles = {TR.APPROVED: [Role.STAFF], TR.DISPATCHED: [Role.STAFF, Role.MANAGER], TR.RECEIVED: [Role.MANAGER],
             TR.CANCELLED: [Role.STAFF]}.get(to)
    if roles:
        notify.notify_roles(db, roles, f"Transfer {tr.transfer_no} {to.lower()}",
                            f"{tr.from_location.name} → {tr.to_location.name}" + (f" · {note}" if note else ""),
                            link="/stock?tab=transfers", channels={"in_app"})


@supplier_return.on_transition
def _return(db: Session, ret: Any, frm: str, to: str, actor: User | None, note: str | None) -> None:
    roles = {RET.APPROVED: [Role.STAFF], RET.REJECTED: [Role.STAFF], RET.CREDIT: [Role.MANAGER]}.get(to)
    if roles:
        notify.notify_roles(db, roles, f"Return {ret.return_no} {to.replace('_', ' ').lower()}",
                            f"{ret.supplier.name}" + (f" · {note}" if note else ""), link="/returns", channels={"in_app"})
