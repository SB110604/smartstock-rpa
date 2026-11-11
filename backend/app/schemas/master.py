import re
from datetime import date

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.common import ORM

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GST_RATES = {0, 0.25, 3, 5, 12, 18, 28}


class LocationIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    type: str = Field("store", pattern="^(store|warehouse)$")
    address: str | None = None
    is_active: bool = True


class LocationOut(ORM):
    id: int
    name: str
    type: str
    address: str | None
    is_active: bool


class CategoryIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class CategoryOut(ORM):
    id: int
    name: str


class ProductIn(BaseModel):
    sku: str = Field(min_length=2, max_length=40)
    barcode: str | None = Field(None, max_length=64)
    name: str = Field(min_length=2, max_length=200)
    category_id: int | None = None
    unit: str = Field("pcs", max_length=12)
    hsn_code: str | None = Field(None, max_length=12)
    gst_rate: float = 0
    cost_price: float = Field(ge=0)
    selling_price: float = Field(ge=0)
    is_perishable: bool = False
    shelf_life_days: int | None = Field(None, ge=1, le=3650)
    min_order_qty: float = Field(1, gt=0)
    pack_size: float = Field(1, gt=0)
    is_active: bool = True

    @field_validator("gst_rate")
    @classmethod
    def _gst(cls, v: float) -> float:
        if v not in GST_RATES:
            raise ValueError("GST rate must be 0, 5, 12, 18 or 28")
        return v

    @field_validator("barcode", "hsn_code")
    @classmethod
    def _blank(cls, v: str | None) -> str | None:
        return v.strip() or None if isinstance(v, str) else v

    @model_validator(mode="after")
    def _perishable(self) -> "ProductIn":
        if self.is_perishable and not self.shelf_life_days:
            raise ValueError("Shelf life is required for perishable products")
        return self


class ProductOut(ORM):
    id: int
    sku: str
    barcode: str | None
    name: str
    category_id: int | None
    category_name: str | None = None
    unit: str
    hsn_code: str | None
    gst_rate: float
    cost_price: float
    selling_price: float
    is_perishable: bool
    shelf_life_days: int | None
    min_order_qty: float
    pack_size: float
    reorder_point: float | None
    safety_stock: float | None
    eoq: float | None
    abc_class: str | None
    xyz_class: str | None
    reorder_paused: bool
    is_active: bool


class ProductListOut(ProductOut):
    on_hand: float = 0
    on_order: float = 0
    available: float = 0
    stock_status: str = "ok"


class SupplierIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    contact_name: str | None = Field(None, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(None, max_length=20)
    gstin: str | None = None
    state: str = Field("Maharashtra", min_length=2, max_length=60)
    address: str | None = None
    payment_terms_days: int = Field(30, ge=0, le=365)
    is_active: bool = True

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.strip().upper()
        if not GSTIN_RE.match(v):
            raise ValueError("GSTIN format is invalid (15 characters, e.g. 27ABCDE1234F1Z5)")
        return v


class SupplierOut(ORM):
    id: int
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    gstin: str | None
    state: str
    address: str | None
    payment_terms_days: int
    is_active: bool


class SupplierListOut(SupplierOut):
    score: float | None = None
    on_time_pct: float | None = None
    products: int = 0


class SupplierProductIn(BaseModel):
    supplier_id: int
    product_id: int
    unit_price: float = Field(gt=0)
    lead_time_days: int = Field(3, ge=0, le=180)
    min_order_qty: float = Field(1, gt=0)
    valid_till: date | None = None


class SupplierProductOut(ORM):
    id: int
    supplier_id: int
    product_id: int
    unit_price: float
    lead_time_days: int
    min_order_qty: float
    valid_till: date | None
    supplier_name: str | None = None
    product_name: str | None = None
    product_sku: str | None = None
