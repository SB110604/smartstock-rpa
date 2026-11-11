from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.permissions import allowed
from app.core.security import decode_token
from app.db.session import get_db
from app.models.core import Role, User

DB = Annotated[Session, Depends(get_db)]


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def get_current_user(request: Request, db: DB) -> User:
    token = _bearer(request)
    if not token:
        raise Unauthorized("Not authenticated")
    data = decode_token(token, "access")
    if not data:
        raise Unauthorized("Invalid or expired token", code="token_invalid")
    user = db.get(User, int(data["sub"]))
    if not user or not user.is_active or user.token_version != data.get("ver"):
        raise Unauthorized("Session is no longer valid", code="token_invalid")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require(permission: str) -> Callable[[User], User]:
    """Route dependency: 403 unless the current user's role grants `permission`."""

    def dep(user: CurrentUser) -> User:
        if not allowed(user.role, permission):
            raise Forbidden("You do not have permission to do this")
        return user

    dep.__name__ = f"require_{permission.replace('.', '_')}"
    return dep


def require_supplier(user: CurrentUser) -> User:
    if user.role != Role.SUPPLIER or not user.supplier_id:
        raise Forbidden("Supplier portal only")
    return user


SupplierUser = Annotated[User, Depends(require_supplier)]
