import datetime as dt
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class Forecast(IdMixin, TimestampMixin, Base):
    __tablename__ = "forecasts"
    __table_args__ = (Index("ix_forecasts_product_date", "product_id", "date"),)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    date: Mapped[dt.date]
    predicted_qty: Mapped[float]
    lower: Mapped[float]
    upper: Mapped[float]
    model_name: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(40))


class ModelRegistry(IdMixin, TimestampMixin, Base):
    __tablename__ = "model_registry"
    name: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(40))
    trained_at: Mapped[datetime]
    metrics: Mapped[dict[str, Any]]
    is_active: Mapped[bool] = mapped_column(default=False)
    file_path: Mapped[str | None]
    notes: Mapped[str | None] = mapped_column(Text)


class SupplierScore(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_scores"
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), index=True)
    computed_at: Mapped[datetime]
    price_score: Mapped[float]
    on_time_pct: Mapped[float]
    avg_lead_days: Mapped[float]
    lead_score: Mapped[float]
    reject_pct: Mapped[float]
    quality_score: Mapped[float]
    total_score: Mapped[float]
    orders_considered: Mapped[int] = mapped_column(default=0)


class Alert(IdMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    type: Mapped[str] = mapped_column(String(30), index=True)
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # info | warning | critical
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    ref_type: Mapped[str | None] = mapped_column(String(40))
    ref_id: Mapped[int | None]
    message: Mapped[str] = mapped_column(Text)
    data_json: Mapped[dict[str, Any] | None]  # suggestions, explanation, numbers behind the alert
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    fingerprint: Mapped[str] = mapped_column(String(120), index=True)  # de-duplicates open alerts
    resolution: Mapped[str | None] = mapped_column(String(40))  # e.g. valid | investigate
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None]


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="in_app")  # in_app | email | telegram
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    title: Mapped[str]
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None]
    sent_at: Mapped[datetime | None]
    read_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)


class AgentRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    agent_name: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | success | failed
    items_processed: Mapped[int] = mapped_column(default=0)
    summary_json: Mapped[dict[str, Any] | None]
    error: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(String(20), default="schedule")  # schedule | manual | seed
    pipeline_id: Mapped[str | None] = mapped_column(String(40))


class Feedback(IdMixin, TimestampMixin, Base):
    __tablename__ = "feedback"
    purchase_request_id: Mapped[int] = mapped_column(ForeignKey("purchase_requests.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    suggested_qty: Mapped[float]
    final_qty: Mapped[float | None]
    decision: Mapped[str] = mapped_column(String(20))  # approved | rejected | edited
    reason: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ChatMessage(IdMixin, TimestampMixin, Base):
    __tablename__ = "chat_messages"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    tool_calls_json: Mapped[list[Any] | None]


class ForecastAccuracy(IdMixin, TimestampMixin, Base):
    """Daily realised accuracy of the active forecast (actual vs predicted) — drives drift alerts and charts."""

    __tablename__ = "forecast_accuracy"
    date: Mapped[dt.date] = mapped_column(index=True)
    mape: Mapped[float]
    products: Mapped[int]
    model_version: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(String(200))
    detail: Mapped[dict[str, Any] | None]
