import datetime as dt
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, JSONType, TimestampMixin


class Role:
    ADMIN = "admin"
    MANAGER = "manager"
    STAFF = "staff"
    SUPPLIER = "supplier"
    ALL = (ADMIN, MANAGER, STAFF, SUPPLIER)
    INTERNAL = (ADMIN, MANAGER, STAFF)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True, index=True)
    phone: Mapped[str | None]
    password_hash: Mapped[str]
    role: Mapped[str] = mapped_column(String(20), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    language: Mapped[str] = mapped_column(String(5), default="en")
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(default=True)
    token_version: Mapped[int] = mapped_column(default=0)
    last_login_at: Mapped[datetime | None]


class PasswordReset(IdMixin, TimestampMixin, Base):
    __tablename__ = "password_resets"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)


class Location(IdMixin, TimestampMixin, Base):
    __tablename__ = "locations"
    name: Mapped[str] = mapped_column(unique=True)
    type: Mapped[str] = mapped_column(String(20), default="store")  # store | warehouse
    address: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(default=True)


class Category(IdMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    name: Mapped[str] = mapped_column(unique=True)


class Festival(IdMixin, TimestampMixin, Base):
    """Indian festival / holiday calendar used as a forecasting feature."""

    __tablename__ = "festivals"
    __table_args__ = (UniqueConstraint("name", "date"),)
    name: Mapped[str]
    date: Mapped[dt.date] = mapped_column(index=True)
    impact: Mapped[float] = mapped_column(default=1.0)  # demand multiplier hint used by the seed generator


class ApiKey(IdMixin, TimestampMixin, Base):
    """API keys for external POS integrations (only the SHA-256 hash is stored)."""

    __tablename__ = "api_keys"
    name: Mapped[str]
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("locations.id"))
    is_active: Mapped[bool] = mapped_column(default=True)
    last_used_at: Mapped[datetime | None]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(40))  # create | update | delete | transition | login ...
    entity: Mapped[str] = mapped_column(String(60), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(60))
    before_json: Mapped[dict[str, Any] | None]
    after_json: Mapped[dict[str, Any] | None]
    ip: Mapped[str | None] = mapped_column(String(64))


class StatusHistory(IdMixin, TimestampMixin, Base):
    """Workflow history for purchase requests, transfers, returns, RFQs (POs use order_status_history)."""

    __tablename__ = "status_history"
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int] = mapped_column(index=True)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user | agent | system | supplier
    actor_id: Mapped[int | None]


class ImportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_jobs"
    entity: Mapped[str] = mapped_column(String(40))
    filename: Mapped[str]
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded | committed
    columns: Mapped[list[Any]]
    rows: Mapped[list[Any]]
    mapping: Mapped[dict[str, Any] | None]
    result: Mapped[dict[str, Any] | None]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReportSchedule(IdMixin, TimestampMixin, Base):
    __tablename__ = "report_schedules"
    report: Mapped[str] = mapped_column(String(40))
    frequency: Mapped[str] = mapped_column(String(20))  # daily | weekly | monthly
    recipients: Mapped[list[Any]]
    fmt: Mapped[str] = mapped_column(String(10), default="pdf")  # pdf | xlsx | both
    is_active: Mapped[bool] = mapped_column(default=True)
    last_sent_at: Mapped[datetime | None]
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
