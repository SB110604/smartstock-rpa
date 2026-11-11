"""Generic state-machine runner. Every workflow status change in the system goes through `transition`,
which validates the move, writes status history + audit log, and fires the machine's hooks
(notifications, follow-up automation). Invalid moves raise InvalidTransition → HTTP 409."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import InvalidTransition
from app.models.core import StatusHistory, User
from app.models.purchasing import OrderStatusHistory
from app.services import audit

Hook = Callable[[Session, Any, str, str, User | None, str | None], None]


@dataclass
class Machine:
    name: str
    transitions: dict[str, set[str]]
    terminal: set[str] = field(default_factory=set)
    hooks: list[Hook] = field(default_factory=list)

    @property
    def states(self) -> set[str]:
        out = set(self.transitions)
        for targets in self.transitions.values():
            out |= targets
        return out

    def can(self, frm: str, to: str) -> bool:
        return to in self.transitions.get(frm, set())

    def on_transition(self, hook: Hook) -> Hook:
        self.hooks.append(hook)
        return hook


def transition(
    db: Session,
    machine: Machine,
    obj: Any,
    to: str,
    *,
    actor: User | None = None,
    actor_type: str | None = None,
    note: str | None = None,
) -> str:
    frm: str = obj.status
    if not machine.can(frm, to):
        raise InvalidTransition(
            f"Cannot change {machine.name.replace('_', ' ')} from {frm} to {to}",
        )
    obj.status = to
    a_type = actor_type or ("user" if actor else "system")
    a_id = actor.id if actor else None
    if machine.name == "purchase_order":
        db.add(
            OrderStatusHistory(
                po_id=obj.id, from_status=frm, to_status=to, note=note, actor_type=a_type, actor_id=a_id
            )
        )
    else:
        db.add(
            StatusHistory(
                entity=machine.name,
                entity_id=obj.id,
                from_status=frm,
                to_status=to,
                note=note,
                actor_type=a_type,
                actor_id=a_id,
            )
        )
    audit.record(db, actor, "transition", machine.name, obj.id, {"status": frm}, {"status": to, "note": note})
    db.flush()
    for hook in machine.hooks:
        hook(db, obj, frm, to, actor, note)
    return frm


def record_initial(
    db: Session,
    machine: Machine,
    obj: Any,
    *,
    actor: User | None,
    actor_type: str | None = None,
    note: str | None = None,
) -> None:
    """History row for the creation state (from_status = None)."""
    a_type = actor_type or ("user" if actor else "system")
    a_id = actor.id if actor else None
    if machine.name == "purchase_order":
        db.add(
            OrderStatusHistory(
                po_id=obj.id,
                from_status=None,
                to_status=obj.status,
                note=note,
                actor_type=a_type,
                actor_id=a_id,
            )
        )
    else:
        db.add(
            StatusHistory(
                entity=machine.name,
                entity_id=obj.id,
                from_status=None,
                to_status=obj.status,
                note=note,
                actor_type=a_type,
                actor_id=a_id,
            )
        )
