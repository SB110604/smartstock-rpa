from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORM


class BatchOut(ORM):
    id: int
    product_id: int
    location_id: int
    batch_no: str
    expiry_date: date | None
    qty_on_hand: float
    cost_price: float
    received_at: datetime
    markdown_pct: float
    is_blocked: bool
    supplier_id: int | None
    product_name: str | None = None
    product_sku: str | None = None
    location_name: str | None = None
    days_to_expiry: int | None = None


class MovementOut(ORM):
    id: int
    product_id: int
    batch_id: int | None
    location_id: int
    type: str
    qty: float
    unit_cost: float
    reference_type: str | None
    reference_id: int | None
    user_id: int | None
    note: str | None
    created_at: datetime
    product_name: str | None = None
    batch_no: str | None = None
    user_name: str | None = None


class StockInIn(BaseModel):
    product_id: int
    location_id: int
    qty: float = Field(gt=0)
    batch_no: str | None = Field(None, max_length=60)
    expiry_date: date | None = None
    cost_price: float | None = Field(None, ge=0)
    supplier_id: int | None = None
    note: str | None = Field(None, max_length=500)


class StockOutIn(BaseModel):
    product_id: int
    location_id: int
    qty: float = Field(gt=0)
    type: str = Field(pattern="^(sale_out|write_off|return_out|adjustment)$")
    batch_id: int | None = None
    reason: str = Field(min_length=3, max_length=500)


class AdjustIn(BaseModel):
    batch_id: int
    new_qty: float = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)


class WriteOffIn(BaseModel):
    batch_id: int
    qty: float | None = Field(None, gt=0)
    reason: str = Field(min_length=3, max_length=500)


class MarkdownIn(BaseModel):
    batch_id: int
    markdown_pct: float = Field(ge=0, le=90)


class LookupOut(BaseModel):
    product: dict | None
    batch: dict | None
    stock: dict | None


class SaleLineIn(BaseModel):
    product_id: int
    qty: float = Field(gt=0)
    unit_price: float | None = Field(None, ge=0)
    discount_pct: float = Field(0, ge=0, le=100)


class SaleIn(BaseModel):
    location_id: int
    customer_name: str | None = Field(None, max_length=120)
    lines: list[SaleLineIn] = Field(min_length=1)


class SaleLineOut(ORM):
    id: int
    product_id: int
    batch_id: int | None
    qty: float
    unit_price: float
    discount_pct: float
    gst_rate: float
    line_total: float
    product_name: str | None = None


class SaleOut(ORM):
    id: int
    invoice_no: str
    location_id: int
    sold_at: datetime
    channel: str
    customer_name: str | None
    subtotal: float
    tax: float
    total: float
    lines: list[SaleLineOut] = []


class PosLineIn(BaseModel):
    sku: str | None = None
    barcode: str | None = None
    qty: float = Field(gt=0)
    unit_price: float | None = Field(None, ge=0)


class PosSaleIn(BaseModel):
    invoice_no: str = Field(min_length=1, max_length=40)
    location_id: int | None = None
    sold_at: datetime | None = None
    lines: list[PosLineIn] = Field(min_length=1)


class CountStartIn(BaseModel):
    location_id: int
    category_id: int | None = None
    product_ids: list[int] | None = None
    note: str | None = None


class CountEntry(BaseModel):
    line_id: int
    counted_qty: float | None = Field(None, ge=0)


class CountEntriesIn(BaseModel):
    entries: list[CountEntry]


class TransferLineIn(BaseModel):
    product_id: int
    qty: float = Field(gt=0)
    batch_id: int | None = None


class TransferIn(BaseModel):
    from_location_id: int
    to_location_id: int
    note: str | None = Field(None, max_length=500)
    lines: list[TransferLineIn] = Field(min_length=1)


class ReasonIn(BaseModel):
    reason: str | None = Field(None, max_length=500)
