import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
import pyotp

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=12 if not settings.is_test else 4)
    ).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _encode(payload: dict[str, Any], expires: timedelta) -> str:
    now = datetime.now(UTC)
    data = {**payload, "iat": int(now.timestamp()), "exp": int((now + expires).timestamp())}
    return jwt.encode(data, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, role: str, token_version: int) -> str:
    return _encode(
        {"sub": str(user_id), "role": role, "ver": token_version, "type": "access"},
        timedelta(minutes=settings.ACCESS_TOKEN_MINUTES),
    )


def create_refresh_token(user_id: int, token_version: int) -> str:
    return _encode(
        {"sub": str(user_id), "ver": token_version, "type": "refresh", "jti": secrets.token_hex(8)},
        timedelta(days=settings.REFRESH_TOKEN_DAYS),
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any] | None:
    try:
        data = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return data if data.get("type") == expected_type else None


def new_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hex). Only the hash is ever stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="SmartStock RPA")


def verify_totp(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    return bool(code) and pyotp.TOTP(secret).verify(code, valid_window=1)
