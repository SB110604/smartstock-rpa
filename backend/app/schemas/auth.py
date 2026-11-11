from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORM


def _strong(v: str) -> str:
    if len(v) < 8 or not any(c.isdigit() for c in v) or not any(c.isalpha() for c in v):
        raise ValueError("Password must be at least 8 characters and contain letters and numbers")
    return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    totp_code: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(ORM):
    id: int
    name: str
    email: str
    phone: str | None
    role: str
    supplier_id: int | None
    language: str
    is_active: bool
    totp_enabled: bool
    telegram_chat_id: str | None
    last_login_at: datetime | None
    created_at: datetime


class MeOut(UserOut):
    permissions: list[str] = []
    supplier_name: str | None = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: MeOut


class MeUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    phone: str | None = Field(None, max_length=20)
    language: str | None = Field(None, pattern="^(en|hi|mr)$")
    telegram_chat_id: str | None = Field(None, max_length=64)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    _v = field_validator("new_password")(_strong)


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str

    _v = field_validator("password")(_strong)


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_png_base64: str


class TotpCode(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)
    role: str = Field(pattern="^(admin|manager|staff|supplier)$")
    supplier_id: int | None = None
    language: str = Field("en", pattern="^(en|hi|mr)$")
    password: str

    _v = field_validator("password")(_strong)


class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    phone: str | None = Field(None, max_length=20)
    role: str | None = Field(None, pattern="^(admin|manager|staff|supplier)$")
    supplier_id: int | None = None
    language: str | None = Field(None, pattern="^(en|hi|mr)$")
    is_active: bool | None = None
    telegram_chat_id: str | None = None
    password: str | None = None

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str | None) -> str | None:
        return None if v in (None, "") else _strong(v)
