from datetime import date
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin
from app.models.core import Category


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    barcode: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    unit: Mapped[str] = mapped_column(String(12), default="pcs")
    hsn_code: Mapped[str | None] = mapped_column(String(12))
    gst_rate: Mapped[float] = mapped_column(default=0)
    cost_price: Mapped[float] = mapped_column(default=0)
    selling_price: Mapped[float] = mapped_column(default=0)
    is_perishable: Mapped[bool] = mapped_column(default=False)
    shelf_life_days: Mapped[int | None]
    min_order_qty: Mapped[float] = mapped_column(default=1)
    pack_size: Mapped[float] = mapped_column(default=1)
    # Computed by the Decision agent (spec 7.3); calc_json keeps every input so the UI can explain them.
    reorder_point: Mapped[float | None]
    safety_stock: Mapped[float | None]
    eoq: Mapped[float | None]
    calc_json: Mapped[dict[str, Any] | None]
    abc_class: Mapped[str | None] = mapped_column(String(1))
    xyz_class: Mapped[str | None] = mapped_column(String(1))
    priority: Mapped[int] = mapped_column(default=0)  # lowered after repeated rejections (spec 7.9)
    reorder_paused: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    category: Mapped[Category | None] = relationship(lazy="joined")


class Supplier(IdMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"
    name: Mapped[str] = mapped_column(unique=True)
    contact_name: Mapped[str | None]
    email: Mapped[str | None]
    phone: Mapped[str | None] = mapped_column(String(20))
    gstin: Mapped[str | None] = mapped_column(String(15))
    state: Mapped[str] = mapped_column(String(60), default="Maharashtra")
    address: Mapped[str | None]
    payment_terms_days: Mapped[int] = mapped_column(default=30)
    is_active: Mapped[bool] = mapped_column(default=True)


class SupplierProduct(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_products"
    __table_args__ = (UniqueConstraint("supplier_id", "product_id"),)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    unit_price: Mapped[float]
    lead_time_days: Mapped[int] = mapped_column(default=3)
    min_order_qty: Mapped[float] = mapped_column(default=1)
    valid_till: Mapped[date | None]

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    product: Mapped[Product] = relationship(lazy="joined")
