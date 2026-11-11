from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select

from app.core.deps import DB, require
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import PageParams, apply_sort, page_params, paginate
from app.core.security import hash_password
from app.models.catalog import Supplier
from app.models.core import Role, User
from app.schemas.auth import UserCreate, UserOut, UserUpdate
from app.schemas.common import Page
from app.services import audit

router = APIRouter(prefix="/users", tags=["users"])
Admin = Annotated[User, Depends(require("users.manage"))]


def _check_supplier_link(db: DB, role: str, supplier_id: int | None) -> None:
    if role == Role.SUPPLIER:
        if not supplier_id or not db.get(Supplier, supplier_id):
            raise ValidationFailed("Supplier users must be linked to an existing supplier")
    elif supplier_id:
        raise ValidationFailed("Only supplier users can be linked to a supplier")


@router.get("", response_model=Page[UserOut])
def list_users(
    admin: Admin,
    db: DB,
    p: Annotated[PageParams, Depends(page_params)],
    q: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> dict:
    stmt = select(User)
    if q:
        stmt = stmt.where(or_(User.name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    if role:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))
    stmt = apply_sort(
        stmt,
        p.sort,
        {"name": User.name, "email": User.email, "role": User.role, "last_login_at": User.last_login_at},
        User.id,
    )
    return paginate(db, stmt, p)


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, admin: Admin, db: DB) -> User:
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise Conflict("A user with this email already exists")
    _check_supplier_link(db, body.role, body.supplier_id)
    user = User(
        **body.model_dump(exclude={"password", "email"}),
        email=body.email.lower(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    audit.created(db, admin, user)
    db.commit()
    return user


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, admin: Admin, db: DB) -> User:
    user = db.get(User, user_id)
    if not user:
        raise NotFound("User not found")
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, admin: Admin, db: DB) -> User:
    user = get_user(user_id, admin, db)
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (
        changes.get("is_active") is False or changes.get("role", Role.ADMIN) != Role.ADMIN
    ):
        raise ValidationFailed("You cannot deactivate or demote your own account")
    role = changes.get("role", user.role)
    _check_supplier_link(
        db,
        role,
        changes.get("supplier_id", user.supplier_id) if role == Role.SUPPLIER else changes.get("supplier_id"),
    )
    if role != Role.SUPPLIER:
        changes["supplier_id"] = None
    password = changes.pop("password", None)
    if password:
        changes["password_hash"] = hash_password(password)
    if password or changes.get("is_active") is False or "role" in changes:
        changes["token_version"] = user.token_version + 1  # force re-login
    audit.apply_update(db, admin, user, changes)
    db.commit()
    return user
