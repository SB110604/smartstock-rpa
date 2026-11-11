from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin
from app.models.catalog import Product
from app.models.core import Location


class MovementType:
    PURCHASE_IN = "purchase_in"
    SALE_OUT = "sale_out"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    RETURN_OUT = "return_out"
    WRITE_OFF = "write_off"
    ALL = (PURCHASE_IN, SALE_OUT, ADJUSTMENT, TRANSFER_IN, TRANSFER_OUT, RETURN_OUT, WRITE_OFF)


class Batch(IdMixin, TimestampMixin, Base):
    __tablename__ = "batches"
    __table_args__ = (Index("ix_batches_product_location", "product_id", "location_id"),)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    batch_no: Mapped[str] = mapped_column(String(60))
    expiry_date: Mapped[date | None] = mapped_column(index=True)
    qty_on_hand: Mapped[float] = mapped_column(default=0)
    cost_price: Mapped[float] = mapped_column(default=0)
    received_at: Mapped[datetime]
    grn_line_id: Mapped[int | None] = mapped_column(ForeignKey("grn_lines.id", ondelete="SET NULL"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    markdown_pct: Mapped[float] = mapped_column(default=0)
    is_blocked: Mapped[bool] = mapped_column(default=False)  # expired / quarantined: never picked for sale

    product: Mapped[Product] = relationship(lazy="joined")
    location: Mapped[Location] = relationship(lazy="joined")


class StockMovement(IdMixin, TimestampMixin, Base):
    __tablename__ = "stock_movements"
    __table_args__ = (Index("ix_movements_product_created", "product_id", "created_at"),)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    type: Mapped[str] = mapped_column(String(20), index=True)
    qty: Mapped[float]  # signed: + into stock, - out of stock
    unit_cost: Mapped[float] = mapped_column(default=0)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    reference_id: Mapped[int | None]
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(lazy="joined")


class Sale(IdMixin, TimestampMixin, Base):
    __tablename__ = "sales"
    invoice_no: Mapped[str] = mapped_column(String(40), unique=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    sold_at: Mapped[datetime] = mapped_column(index=True)
    channel: Mapped[str] = mapped_column(String(20), default="manual")  # pos_api | manual
    customer_name: Mapped[str | None]
    subtotal: Mapped[float] = mapped_column(default=0)
    tax: Mapped[float] = mapped_column(default=0)
    total: Mapped[float] = mapped_column(default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    lines: Mapped[list["SaleLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class SaleLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "sale_lines"
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"))
    qty: Mapped[float]
    unit_price: Mapped[float]
    discount_pct: Mapped[float] = mapped_column(default=0)
    gst_rate: Mapped[float] = mapped_column(default=0)
    line_total: Mapped[float] = mapped_column(default=0)

    product: Mapped[Product] = relationship(lazy="joined")


class StockCount(IdMixin, TimestampMixin, Base):
    __tablename__ = "stock_counts"
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(
        String(20), default="in_progress"
    )  # in_progress | completed | cancelled
    note: Mapped[str | None] = mapped_column(Text)
    started_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None]

    location: Mapped[Location] = relationship(lazy="joined")
    lines: Mapped[list["StockCountLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class StockCountLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "stock_count_lines"
    count_id: Mapped[int] = mapped_column(ForeignKey("stock_counts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"))
    system_qty: Mapped[float] = mapped_column(default=0)
    counted_qty: Mapped[float | None]
    variance: Mapped[float | None]

    product: Mapped[Product] = relationship(lazy="joined")


class StockTransfer(IdMixin, TimestampMixin, Base):
    __tablename__ = "stock_transfers"
    transfer_no: Mapped[str] = mapped_column(String(30), unique=True)
    from_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    to_location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")
    note: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    dispatched_at: Mapped[datetime | None]
    received_at: Mapped[datetime | None]

    from_location: Mapped[Location] = relationship(foreign_keys=[from_location_id], lazy="joined")
    to_location: Mapped[Location] = relationship(foreign_keys=[to_location_id], lazy="joined")
    lines: Mapped[list["StockTransferLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class StockTransferLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "stock_transfer_lines"
    transfer_id: Mapped[int] = mapped_column(ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"))
    qty: Mapped[float]

    product: Mapped[Product] = relationship(lazy="joined")
