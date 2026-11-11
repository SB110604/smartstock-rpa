import base64
import io
from datetime import timedelta

import qrcode
from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.core import ratelimit
from app.core.config import settings
from app.core.deps import DB, CurrentUser
from app.core.errors import AppError, Forbidden, Unauthorized, ValidationFailed
from app.core.permissions import permissions_for
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    new_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.core.timeutil import now
from app.models.catalog import Supplier
from app.models.core import PasswordReset, Role, User
from app.schemas.auth import (
    ForgotIn,
    LoginIn,
    MeOut,
    MeUpdate,
    PasswordChange,
    RefreshIn,
    ResetIn,
    TokenOut,
    TotpCode,
    TotpSetupOut,
)
from app.schemas.common import Message
from app.services import audit, mailer

router = APIRouter(prefix="/auth", tags=["auth"])


def me_out(db: DB, user: User) -> MeOut:
    out = MeOut.model_validate(user)
    out.permissions = permissions_for(user.role)
    if user.supplier_id:
        sup = db.get(Supplier, user.supplier_id)
        out.supplier_name = sup.name if sup else None
    return out


def issue_tokens(db: DB, user: User) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, user.role, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
        user=me_out(db, user),
    )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: DB) -> TokenOut:
    ip = request.client.host if request.client else "unknown"
    key = f"login:{ip}:{body.email.lower()}"
    ratelimit.hit(key, settings.LOGIN_RATE_LIMIT_PER_MINUTE)
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise Unauthorized("Incorrect email or password", code="invalid_credentials")
    if not user.is_active:
        raise Unauthorized("This account is disabled", code="account_disabled")
    if user.totp_enabled and user.totp_secret:
        if not body.totp_code:
            raise AppError(
                "Enter the 6-digit code from your authenticator app", code="totp_required", status_code=401
            )
        if not verify_totp(user.totp_secret, body.totp_code):
            raise Unauthorized("Invalid authentication code", code="totp_invalid")
    ratelimit.reset(key)
    user.last_login_at = now()
    audit.record(db, user, "login", "users", user.id)
    db.commit()
    return issue_tokens(db, user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: DB) -> TokenOut:
    data = decode_token(body.refresh_token, "refresh")
    user = db.get(User, int(data["sub"])) if data else None
    if not data or not user or not user.is_active or user.token_version != data.get("ver"):
        raise Unauthorized("Session expired, please log in again", code="token_invalid")
    return issue_tokens(db, user)


@router.post("/logout", response_model=Message)
def logout(user: CurrentUser, db: DB) -> Message:
    user.token_version += 1  # invalidates every outstanding access/refresh token
    audit.record(db, user, "logout", "users", user.id)
    db.commit()
    return Message(detail="Logged out")


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser, db: DB) -> MeOut:
    return me_out(db, user)


@router.patch("/me", response_model=MeOut)
def update_me(body: MeUpdate, user: CurrentUser, db: DB) -> MeOut:
    audit.apply_update(db, user, user, body.model_dump(exclude_unset=True), "users")
    db.commit()
    return me_out(db, user)


@router.post("/change-password", response_model=Message)
def change_password(body: PasswordChange, user: CurrentUser, db: DB) -> Message:
    if not verify_password(body.current_password, user.password_hash):
        raise ValidationFailed("Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit.record(db, user, "password_change", "users", user.id)
    db.commit()
    return Message(detail="Password changed. Please log in again.")


@router.post("/forgot-password", response_model=Message)
def forgot_password(body: ForgotIn, request: Request, db: DB) -> Message:
    ip = request.client.host if request.client else "unknown"
    ratelimit.hit(f"forgot:{ip}", 5)
    user = db.scalar(
        select(User).where(func.lower(User.email) == body.email.lower(), User.is_active.is_(True))
    )
    if user:
        raw, digest = new_token()
        db.add(PasswordReset(user_id=user.id, token_hash=digest, expires_at=now() + timedelta(hours=1)))
        db.commit()
        link = f"{settings.FRONTEND_URL}/reset-password?token={raw}"
        html = mailer.layout(
            "Reset your password",
            f"<p>Hello {user.name},</p><p>Use the button below to choose a new password. "
            f"The link is valid for 1 hour and can be used once.</p>{mailer.button(link, 'Reset password')}"
            "<p>If you did not ask for this, you can ignore this email.</p>",
        )
        mailer.send_email(
            user.email, "SmartStock RPA — password reset", html, text=f"Reset your password: {link}"
        )
    # Same answer whether or not the account exists (no user enumeration).
    return Message(detail="If the email is registered, a reset link has been sent.")


@router.post("/reset-password", response_model=Message)
def reset_password(body: ResetIn, db: DB) -> Message:
    pr = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(body.token)))
    if not pr or pr.used_at or pr.expires_at < now():
        raise ValidationFailed("This reset link is invalid or has expired")
    user = db.get(User, pr.user_id)
    if not user:
        raise ValidationFailed("This reset link is invalid or has expired")
    user.password_hash = hash_password(body.password)
    user.token_version += 1
    pr.used_at = now()
    audit.record(db, user, "password_reset", "users", user.id)
    db.commit()
    return Message(detail="Password updated. You can log in now.")


@router.post("/2fa/setup", response_model=TotpSetupOut)
def totp_setup(user: CurrentUser, db: DB) -> TotpSetupOut:
    if user.role != Role.ADMIN:
        raise Forbidden("Two-factor authentication is available for admin accounts")
    if user.totp_enabled:
        raise ValidationFailed("Two-factor authentication is already enabled")
    user.totp_secret = new_totp_secret()
    db.commit()
    uri = totp_uri(user.totp_secret, user.email)
    img = qrcode.make(uri, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return TotpSetupOut(
        secret=user.totp_secret, otpauth_uri=uri, qr_png_base64=base64.b64encode(buf.getvalue()).decode()
    )


@router.post("/2fa/enable", response_model=MeOut)
def totp_enable(body: TotpCode, user: CurrentUser, db: DB) -> MeOut:
    if not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        raise ValidationFailed("Invalid code — check the time on your phone and try again")
    user.totp_enabled = True
    audit.record(db, user, "2fa_enable", "users", user.id)
    db.commit()
    return me_out(db, user)


@router.post("/2fa/disable", response_model=MeOut)
def totp_disable(body: TotpCode, user: CurrentUser, db: DB) -> MeOut:
    if not user.totp_enabled or not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        raise ValidationFailed("Invalid code")
    user.totp_enabled = False
    user.totp_secret = None
    audit.record(db, user, "2fa_disable", "users", user.id)
    db.commit()
    return me_out(db, user)
