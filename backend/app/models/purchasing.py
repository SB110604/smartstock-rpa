from datetime import date, datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin
from app.models.catalog import Product, Supplier
from app.models.core import Location


class PurchaseRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchase_requests"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    suggested_qty: Mapped[float]
    final_qty: Mapped[float | None]
    suggested_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    final_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    est_unit_price: Mapped[float] = mapped_column(default=0)
    est_total: Mapped[float] = mapped_column(default=0)
    reason_json: Mapped[dict[str, Any] | None]
    reason_text: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(20), default="agent")  # agent | user
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    required_levels: Mapped[int] = mapped_column(default=0)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    po_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="SET NULL", use_alter=True)
    )
    submitted_at: Mapped[datetime | None]

    product: Mapped[Product] = relationship(lazy="joined")
    location: Mapped[Location] = relationship(lazy="joined")
    suggested_supplier: Mapped[Supplier | None] = relationship(
        foreign_keys=[suggested_supplier_id], lazy="joined"
    )
    final_supplier: Mapped[Supplier | None] = relationship(foreign_keys=[final_supplier_id], lazy="joined")
    approvals: Mapped[list["Approval"]] = relationship(
        lazy="selectin", order_by="Approval.level", cascade="all, delete-orphan"
    )


class ApprovalRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "approval_rules"
    min_amount: Mapped[float] = mapped_column(default=0)
    max_amount: Mapped[float | None]
    approver_role: Mapped[str | None] = mapped_column(String(20))
    auto_approve: Mapped[bool] = mapped_column(default=False)


class Approval(IdMixin, TimestampMixin, Base):
    __tablename__ = "approvals"
    purchase_request_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_requests.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[int]
    approver_role: Mapped[str] = mapped_column(String(20))
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | approved | rejected | skipped
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    via: Mapped[str | None] = mapped_column(String(20))  # web | email_link | telegram | auto
    reminded_at: Mapped[datetime | None]
    escalated_at: Mapped[datetime | None]


class ApprovalToken(IdMixin, TimestampMixin, Base):
    __tablename__ = "approval_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    approval_id: Mapped[int] = mapped_column(ForeignKey("approvals.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(10))  # approve | reject
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]


class Rfq(IdMixin, TimestampMixin, Base):
    __tablename__ = "rfqs"
    rfq_no: Mapped[str] = mapped_column(String(30), unique=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN | CLOSED | AWARDED | CANCELLED
    due_date: Mapped[date | None]
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    items: Mapped[list["RfqItem"]] = relationship(lazy="selectin", cascade="all, delete-orphan")
    suppliers: Mapped[list["RfqSupplier"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class RfqItem(IdMixin, TimestampMixin, Base):
    __tablename__ = "rfq_items"
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    qty: Mapped[float]

    product: Mapped[Product] = relationship(lazy="joined")


class RfqSupplier(IdMixin, TimestampMixin, Base):
    __tablename__ = "rfq_suppliers"
    rfq_id: Mapped[int] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    invited_at: Mapped[datetime | None]
    responded_at: Mapped[datetime | None]

    supplier: Mapped[Supplier] = relationship(lazy="joined")


class SupplierQuote(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_quotes"
    rfq_id: Mapped[int | None] = mapped_column(ForeignKey("rfqs.id", ondelete="CASCADE"), index=True)
    rfq_item_id: Mapped[int | None] = mapped_column(ForeignKey("rfq_items.id", ondelete="CASCADE"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    unit_price: Mapped[float]
    lead_time_days: Mapped[int | None]
    min_order_qty: Mapped[float | None]
    valid_till: Mapped[date | None]
    status: Mapped[str] = mapped_column(
        String(20), default="submitted"
    )  # submitted|pending_review|accepted|rejected
    source: Mapped[str] = mapped_column(String(20), default="portal")  # portal | email
    note: Mapped[str | None] = mapped_column(Text)

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    product: Mapped[Product] = relationship(lazy="joined")


class PurchaseOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    po_no: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(String(30), default="CREATED", index=True)
    order_date: Mapped[date]
    expected_date: Mapped[date | None]  # required-by date
    predicted_date: Mapped[date | None]  # tracking agent prediction
    supplier_eta: Mapped[date | None]
    is_interstate: Mapped[bool] = mapped_column(default=False)
    subtotal: Mapped[float] = mapped_column(default=0)
    cgst: Mapped[float] = mapped_column(default=0)
    sgst: Mapped[float] = mapped_column(default=0)
    igst: Mapped[float] = mapped_column(default=0)
    total: Mapped[float] = mapped_column(default=0)
    pdf_path: Mapped[str | None]
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]
    dispatched_at: Mapped[datetime | None]
    tracking_ref: Mapped[str | None] = mapped_column(String(80))
    courier_name: Mapped[str | None] = mapped_column(String(80))
    courier_status: Mapped[str | None] = mapped_column(String(80))
    delivered_at: Mapped[datetime | None]
    closed_at: Mapped[datetime | None]
    reminder_sent_at: Mapped[datetime | None]
    escalated_at: Mapped[datetime | None]

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    location: Mapped[Location] = relationship(lazy="joined")
    lines: Mapped[list["PoLine"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="PoLine.id"
    )


class PoLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "po_lines"
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    purchase_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_requests.id", ondelete="SET NULL")
    )
    qty: Mapped[float]
    unit_price: Mapped[float]
    gst_rate: Mapped[float] = mapped_column(default=0)
    hsn_code: Mapped[str | None] = mapped_column(String(12))
    received_qty: Mapped[float] = mapped_column(default=0)
    damaged_qty: Mapped[float] = mapped_column(default=0)

    product: Mapped[Product] = relationship(lazy="joined")


class OrderStatusHistory(IdMixin, TimestampMixin, Base):
    __tablename__ = "order_status_history"
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")
    actor_id: Mapped[int | None]


class GoodsReceipt(IdMixin, TimestampMixin, Base):
    __tablename__ = "goods_receipts"
    grn_no: Mapped[str] = mapped_column(String(30), unique=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    received_at: Mapped[datetime]
    note: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["GrnLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class GrnLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "grn_lines"
    grn_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True)
    po_line_id: Mapped[int] = mapped_column(ForeignKey("po_lines.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    received_qty: Mapped[float]
    damaged_qty: Mapped[float] = mapped_column(default=0)
    batch_no: Mapped[str] = mapped_column(String(60))
    expiry_date: Mapped[date | None]

    product: Mapped[Product] = relationship(lazy="joined")


class SupplierInvoice(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_invoices"
    invoice_no: Mapped[str] = mapped_column(String(60))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    invoice_date: Mapped[date]
    subtotal: Mapped[float] = mapped_column(default=0)
    tax: Mapped[float] = mapped_column(default=0)
    total: Mapped[float] = mapped_column(default=0)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | ocr | portal
    file_path: Mapped[str | None]
    ocr_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default="received"
    )  # received | matched | mismatch | resolved
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    lines: Mapped[list["SupplierInvoiceLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class SupplierInvoiceLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_invoice_lines"
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_invoices.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id", ondelete="SET NULL"))
    description: Mapped[str | None]
    qty: Mapped[float]
    unit_price: Mapped[float]
    gst_rate: Mapped[float] = mapped_column(default=0)


class ThreeWayMatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "three_way_matches"
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    grn_id: Mapped[int | None] = mapped_column(ForeignKey("goods_receipts.id", ondelete="SET NULL"))
    invoice_id: Mapped[int] = mapped_column(ForeignKey("supplier_invoices.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20))  # matched | mismatch | resolved
    details_json: Mapped[dict[str, Any]]
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None]
    resolution_note: Mapped[str | None] = mapped_column(Text)


class SupplierReturn(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_returns"
    return_no: Mapped[str] = mapped_column(String(30), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id", ondelete="SET NULL"))
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id"))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    reason: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[float] = mapped_column(default=0)
    tax: Mapped[float] = mapped_column(default=0)
    total: Mapped[float] = mapped_column(default=0)
    debit_note_no: Mapped[str | None] = mapped_column(String(30))
    pdf_path: Mapped[str | None]
    credit_note_ref: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    lines: Mapped[list["SupplierReturnLine"]] = relationship(lazy="selectin", cascade="all, delete-orphan")


class SupplierReturnLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "supplier_return_lines"
    return_id: Mapped[int] = mapped_column(ForeignKey("supplier_returns.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"))
    qty: Mapped[float]
    unit_price: Mapped[float]
    gst_rate: Mapped[float] = mapped_column(default=0)
    reason: Mapped[str | None]

    product: Mapped[Product] = relationship(lazy="joined")
