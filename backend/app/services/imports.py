"""CSV / Excel import: upload → auto column mapping → per-row validation preview → commit valid rows.

Supported entities: products, suppliers, supplier_prices, opening_stock, sales_history (spec 6.2)."""

import csv
import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from rapidfuzz import fuzz, process, utils
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import TZ
from app.models.catalog import Product, Supplier, SupplierProduct
from app.models.core import Category, ImportJob, Location, User
from app.models.inventory import Sale, SaleLine
from app.services import audit, stock

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GST_RATES = {0.0, 0.25, 3.0, 5.0, 12.0, 18.0, 28.0}
MAX_ROWS = 20000


@dataclass
class F:
    name: str
    type: str = "str"  # str | int | float | bool | date
    required: bool = False
    aliases: tuple[str, ...] = ()
    example: str = ""


@dataclass
class EntitySpec:
    label: str
    fields: list[F]
    commit_row: Callable[[Session, dict[str, Any], User, dict[str, Any]], str] = field(repr=False)
    check_row: Callable[[Session, dict[str, Any], dict[str, Any]], list[str]] = field(repr=False)


# ---------------------------------------------------------------- parsing helpers


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%b-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("use DD-MM-YYYY")


def coerce(f: F, raw: Any) -> Any:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        if f.required:
            raise ValueError("is required")
        return None
    if f.type == "str":
        return str(raw).strip()
    if f.type == "int":
        return int(float(str(raw).replace(",", "")))
    if f.type == "float":
        return float(str(raw).replace(",", "").replace("₹", "").strip())
    if f.type == "bool":
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "y"):
            return True
        if s in ("0", "false", "no", "n"):
            return False
        raise ValueError("must be yes/no")
    if f.type == "date":
        return parse_date(raw)
    return raw


def read_file(content: bytes, filename: str) -> tuple[list[str], list[dict[str, Any]]]:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True)) if ws is not None else []
        if not rows:
            raise ValidationFailed("The spreadsheet is empty")
        headers = [str(h).strip() if h is not None else f"column_{i + 1}" for i, h in enumerate(rows[0])]
        data = [
            {
                headers[i]: (v.isoformat() if isinstance(v, datetime | date) else v)
                for i, v in enumerate(r)
                if i < len(headers)
            }
            for r in rows[1:]
            if any(v not in (None, "") for v in r)
        ]
    elif name.endswith((".csv", ".txt")):
        text = content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        headers = [h.strip() for h in (reader.fieldnames or [])]
        data = [
            {(k or "").strip(): v for k, v in r.items()}
            for r in reader
            if any((v or "").strip() for v in r.values())
        ]
    else:
        raise ValidationFailed("Upload a .csv or .xlsx file")
    if not headers:
        raise ValidationFailed("No header row found")
    if len(data) > MAX_ROWS:
        raise ValidationFailed(f"Too many rows (max {MAX_ROWS})")
    return headers, data


def auto_map(headers: list[str], spec: EntitySpec) -> dict[str, str | None]:
    """Field → column. Exact/alias match on normalised names first, then fuzzy (score ≥ 85)."""
    norm = {_norm(h): h for h in headers}
    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    for f in spec.fields:
        candidates = [_norm(f.name), *(_norm(a) for a in f.aliases)]
        hit = next((norm[c] for c in candidates if c in norm and norm[c] not in used), None)
        if hit is None:
            free = [h for h in headers if h not in used]
            best = (
                process.extractOne(f.name.replace("_", " "), free, scorer=fuzz.token_sort_ratio, processor=utils.default_process)
                if free
                else None
            )
            if best and best[1] >= 85:
                hit = best[0]
        if hit:
            used.add(hit)
        mapping[f.name] = hit
    return mapping


# ---------------------------------------------------------------- entity rules


def _product_by_sku(db: Session, cache: dict[str, Any], sku: str) -> Product | None:
    key = f"p:{sku}"
    if key not in cache:
        cache[key] = db.scalar(select(Product).where(Product.sku == sku))
    return cache[key]


def _supplier_by_name(db: Session, cache: dict[str, Any], name: str) -> Supplier | None:
    key = f"s:{name.lower()}"
    if key not in cache:
        cache[key] = db.scalar(select(Supplier).where(Supplier.name.ilike(name)))
    return cache[key]


def _location_by_name(db: Session, cache: dict[str, Any], name: str | None) -> Location | None:
    key = f"l:{(name or '').lower()}"
    if key not in cache:
        stmt = select(Location).order_by(Location.id)
        cache[key] = db.scalar(stmt.where(Location.name.ilike(name)) if name else stmt)
    return cache[key]


def _check_product(db: Session, r: dict[str, Any], c: dict[str, Any]) -> list[str]:
    errs = []
    if r["gst_rate"] is not None and r["gst_rate"] not in GST_RATES:
        errs.append("gst_rate must be one of 0, 5, 12, 18, 28")
    if (
        r["selling_price"] is not None
        and r["cost_price"] is not None
        and r["selling_price"] < r["cost_price"]
    ):
        errs.append("selling_price is below cost_price")
    for k in ("cost_price", "selling_price", "pack_size", "min_order_qty"):
        if r.get(k) is not None and r[k] < 0:
            errs.append(f"{k} cannot be negative")
    if r.get("is_perishable") and not r.get("shelf_life_days"):
        errs.append("shelf_life_days is required for perishables")
    if r.get("barcode"):
        other = db.scalar(select(Product).where(Product.barcode == r["barcode"]))
        if other and other.sku != r["sku"]:
            errs.append(f"barcode already used by {other.sku}")
    return errs


def _commit_product(db: Session, r: dict[str, Any], user: User, c: dict[str, Any]) -> str:
    cat_id = None
    if r.get("category"):
        cat = db.scalar(select(Category).where(Category.name.ilike(r["category"])))
        if not cat:
            cat = Category(name=r["category"])
            db.add(cat)
            db.flush()
        cat_id = cat.id
    values = {k: v for k, v in r.items() if k != "category" and v is not None}
    if cat_id:
        values["category_id"] = cat_id
    existing = _product_by_sku(db, c, r["sku"])
    if existing:
        audit.apply_update(db, user, existing, values)
        return "updated"
    p = Product(**values)
    db.add(p)
    audit.created(db, user, p)
    c[f"p:{p.sku}"] = p
    return "created"


def _check_supplier(db: Session, r: dict[str, Any], c: dict[str, Any]) -> list[str]:
    errs = []
    if r.get("gstin") and not GSTIN_RE.match(r["gstin"].upper()):
        errs.append("gstin format is invalid")
    if r.get("email") and not EMAIL_RE.match(r["email"]):
        errs.append("email is invalid")
    return errs


def _commit_supplier(db: Session, r: dict[str, Any], user: User, c: dict[str, Any]) -> str:
    values = {k: v for k, v in r.items() if v is not None}
    if values.get("gstin"):
        values["gstin"] = values["gstin"].upper()
    existing = _supplier_by_name(db, c, r["name"])
    if existing:
        audit.apply_update(db, user, existing, values)
        return "updated"
    s = Supplier(**values)
    db.add(s)
    audit.created(db, user, s)
    c[f"s:{s.name.lower()}"] = s
    return "created"


def _check_price(db: Session, r: dict[str, Any], c: dict[str, Any]) -> list[str]:
    errs = []
    if not _supplier_by_name(db, c, r["supplier"]):
        errs.append(f"unknown supplier '{r['supplier']}'")
    if not _product_by_sku(db, c, r["sku"]):
        errs.append(f"unknown sku '{r['sku']}'")
    if r["unit_price"] is not None and r["unit_price"] <= 0:
        errs.append("unit_price must be positive")
    return errs


def _commit_price(db: Session, r: dict[str, Any], user: User, c: dict[str, Any]) -> str:
    sup = _supplier_by_name(db, c, r["supplier"])
    prod = _product_by_sku(db, c, r["sku"])
    assert sup and prod
    values = {
        "unit_price": r["unit_price"],
        "lead_time_days": r.get("lead_time_days") or 3,
        "min_order_qty": r.get("min_order_qty") or 1,
        "valid_till": r.get("valid_till"),
    }
    sp = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.supplier_id == sup.id, SupplierProduct.product_id == prod.id
        )
    )
    if sp:
        audit.apply_update(db, user, sp, values)
        return "updated"
    sp = SupplierProduct(supplier_id=sup.id, product_id=prod.id, **values)
    db.add(sp)
    audit.created(db, user, sp)
    return "created"


def _check_stock(db: Session, r: dict[str, Any], c: dict[str, Any]) -> list[str]:
    errs = []
    p = _product_by_sku(db, c, r["sku"])
    if not p:
        errs.append(f"unknown sku '{r['sku']}'")
    if not _location_by_name(db, c, r.get("location")):
        errs.append(f"unknown location '{r.get('location')}'")
    if r["qty"] is not None and r["qty"] <= 0:
        errs.append("qty must be positive")
    if p and p.is_perishable and not r.get("expiry_date") and not p.shelf_life_days:
        errs.append("expiry_date is required for this perishable product")
    return errs


def _commit_stock(db: Session, r: dict[str, Any], user: User, c: dict[str, Any]) -> str:
    p = _product_by_sku(db, c, r["sku"])
    loc = _location_by_name(db, c, r.get("location"))
    assert p and loc
    stock.receive(
        db,
        product=p,
        location_id=loc.id,
        qty=r["qty"],
        batch_no=r.get("batch_no"),
        expiry_date=r.get("expiry_date"),
        unit_cost=r.get("cost_price"),
        user=user,
        ref_type="opening_stock",
        movement_type="adjustment",
        note="Opening stock import",
    )
    return "created"


def _check_sale(db: Session, r: dict[str, Any], c: dict[str, Any]) -> list[str]:
    errs = []
    if not _product_by_sku(db, c, r["sku"]):
        errs.append(f"unknown sku '{r['sku']}'")
    if not _location_by_name(db, c, r.get("location")):
        errs.append(f"unknown location '{r.get('location')}'")
    if r["qty"] is not None and r["qty"] <= 0:
        errs.append("qty must be positive")
    return errs


def _commit_sale(db: Session, r: dict[str, Any], user: User, c: dict[str, Any]) -> str:
    """Historical sales feed forecasting only; they do not move current stock (batch_id is empty)."""
    p = _product_by_sku(db, c, r["sku"])
    loc = _location_by_name(db, c, r.get("location"))
    assert p and loc
    key = f"inv:{r['invoice_no']}"
    sale = c.get(key) or db.scalar(select(Sale).where(Sale.invoice_no == r["invoice_no"]))
    if sale is None:
        d: date = r["date"]
        sale = Sale(
            invoice_no=r["invoice_no"],
            location_id=loc.id,
            sold_at=datetime(d.year, d.month, d.day, 12, tzinfo=TZ),
            channel="import",
            user_id=user.id,
        )
        db.add(sale)
        db.flush()
    c[key] = sale
    price = r.get("unit_price") if r.get("unit_price") is not None else p.selling_price
    total = round(price * r["qty"], 2)
    tax = round(total * p.gst_rate / (100 + p.gst_rate), 2)
    db.add(
        SaleLine(
            sale_id=sale.id,
            product_id=p.id,
            qty=r["qty"],
            unit_price=price,
            gst_rate=p.gst_rate,
            line_total=total,
        )
    )
    sale.total = round(sale.total + total, 2)
    sale.tax = round(sale.tax + tax, 2)
    sale.subtotal = round(sale.total - sale.tax, 2)
    return "created"


SPECS: dict[str, EntitySpec] = {
    "products": EntitySpec(
        "Products",
        [
            F("sku", required=True, aliases=("item code", "code", "product code"), example="STP-001"),
            F(
                "name",
                required=True,
                aliases=("product", "product name", "item", "description"),
                example="Basmati Rice 5kg",
            ),
            F("category", aliases=("category name", "group"), example="Staples"),
            F("barcode", aliases=("ean", "upc", "gtin"), example="8901234567890"),
            F("unit", aliases=("uom",), example="pcs"),
            F("hsn_code", aliases=("hsn", "hsn sac"), example="1006"),
            F("gst_rate", "float", aliases=("gst", "gst %", "tax rate"), example="5"),
            F("cost_price", "float", required=True, aliases=("cost", "purchase price"), example="420"),
            F("selling_price", "float", required=True, aliases=("price", "mrp", "sale price"), example="499"),
            F("is_perishable", "bool", aliases=("perishable",), example="no"),
            F("shelf_life_days", "int", aliases=("shelf life",), example=""),
            F("min_order_qty", "float", aliases=("moq",), example="10"),
            F("pack_size", "float", aliases=("pack", "case size"), example="10"),
        ],
        _commit_product,
        _check_product,
    ),
    "suppliers": EntitySpec(
        "Suppliers",
        [
            F(
                "name",
                required=True,
                aliases=("supplier", "supplier name", "vendor"),
                example="Pune Agro Traders",
            ),
            F("contact_name", aliases=("contact", "contact person"), example="Rahul Patil"),
            F("email", aliases=("email id", "mail"), example="orders@puneagro.in"),
            F("phone", aliases=("mobile", "phone no"), example="9822012345"),
            F("gstin", aliases=("gst no", "gst number"), example="27ABCDE1234F1Z5"),
            F("state", required=True, aliases=("state name",), example="Maharashtra"),
            F("address", example="Market Yard, Pune"),
            F("payment_terms_days", "int", aliases=("credit days", "payment terms"), example="30"),
        ],
        _commit_supplier,
        _check_supplier,
    ),
    "supplier_prices": EntitySpec(
        "Supplier prices",
        [
            F("supplier", required=True, aliases=("supplier name", "vendor"), example="Pune Agro Traders"),
            F("sku", required=True, aliases=("item code", "product code"), example="STP-001"),
            F("unit_price", "float", required=True, aliases=("price", "rate", "cost"), example="410"),
            F("lead_time_days", "int", aliases=("lead time", "lead days"), example="3"),
            F("min_order_qty", "float", aliases=("moq",), example="10"),
            F("valid_till", "date", aliases=("valid until", "validity"), example="31-03-2027"),
        ],
        _commit_price,
        _check_price,
    ),
    "opening_stock": EntitySpec(
        "Opening stock",
        [
            F("sku", required=True, aliases=("item code", "product code"), example="STP-001"),
            F("location", aliases=("store", "warehouse"), example="Main Store"),
            F("qty", "float", required=True, aliases=("quantity", "stock", "on hand"), example="40"),
            F("batch_no", aliases=("batch", "lot"), example="RB2611"),
            F("expiry_date", "date", aliases=("expiry", "exp date", "best before"), example="30-06-2027"),
            F("cost_price", "float", aliases=("cost", "rate"), example="420"),
        ],
        _commit_stock,
        _check_stock,
    ),
    "sales_history": EntitySpec(
        "Sales history",
        [
            F("invoice_no", required=True, aliases=("invoice", "bill no", "bill number"), example="H-000123"),
            F("date", "date", required=True, aliases=("sale date", "bill date"), example="15-10-2026"),
            F("sku", required=True, aliases=("item code", "product code"), example="STP-001"),
            F("qty", "float", required=True, aliases=("quantity",), example="2"),
            F("unit_price", "float", aliases=("price", "rate"), example="499"),
            F("location", aliases=("store",), example="Main Store"),
        ],
        _commit_sale,
        _check_sale,
    ),
}


def spec_for(entity: str) -> EntitySpec:
    if entity not in SPECS:
        raise NotFound(f"Unknown import type '{entity}'")
    return SPECS[entity]


def describe() -> list[dict[str, Any]]:
    return [
        {
            "entity": k,
            "label": s.label,
            "fields": [{"name": f.name, "type": f.type, "required": f.required} for f in s.fields],
        }
        for k, s in SPECS.items()
    ]


# ---------------------------------------------------------------- job lifecycle


def upload(db: Session, entity: str, filename: str, content: bytes, user: User) -> ImportJob:
    spec = spec_for(entity)
    headers, rows = read_file(content, filename)
    job = ImportJob(
        entity=entity,
        filename=filename,
        columns=headers,
        rows=[{k: _jsonable(v) for k, v in r.items()} for r in rows],
        mapping=auto_map(headers, spec),
        created_by=user.id,
    )
    db.add(job)
    db.commit()
    return job


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def get_job(db: Session, job_id: int, user: User) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if not job:
        raise NotFound("Import not found")
    return job


def _validate_rows(db: Session, job: ImportJob, mapping: dict[str, str | None]) -> list[dict[str, Any]]:
    spec = spec_for(job.entity)
    missing = [f.name for f in spec.fields if f.required and not mapping.get(f.name)]
    if missing:
        raise ValidationFailed(f"Map the required field(s): {', '.join(missing)}")
    cache: dict[str, Any] = {}
    seen_keys: set[str] = set()
    out = []
    for i, raw in enumerate(job.rows, start=2):  # row 1 is the header
        values: dict[str, Any] = {}
        errors: list[str] = []
        for f in spec.fields:
            col = mapping.get(f.name)
            try:
                values[f.name] = coerce(f, raw.get(col) if col else None)
            except (ValueError, TypeError) as exc:
                errors.append(f"{f.name} {exc}" if str(exc) else f"{f.name} is invalid")
                values[f.name] = None
        if not errors:
            errors.extend(spec.check_row(db, values, cache))
            key = {"products": "sku", "suppliers": "name"}.get(job.entity)
            if key and values.get(key):
                k = str(values[key]).lower()
                if k in seen_keys:
                    errors.append(f"duplicate {key} in file")
                seen_keys.add(k)
        out.append(
            {
                "row": i,
                "values": {k: _jsonable(v) for k, v in values.items()},
                "errors": errors,
                "_typed": values,
            }
        )
    return out


def preview(db: Session, job: ImportJob, mapping: dict[str, str | None], limit: int = 200) -> dict[str, Any]:
    rows = _validate_rows(db, job, mapping)
    job.mapping = mapping
    db.commit()
    bad = [r for r in rows if r["errors"]]
    return {
        "job_id": job.id,
        "entity": job.entity,
        "total": len(rows),
        "valid": len(rows) - len(bad),
        "invalid": len(bad),
        "rows": [{k: v for k, v in r.items() if k != "_typed"} for r in rows[:limit]],
        "error_rows": [{k: v for k, v in r.items() if k != "_typed"} for r in bad[:limit]],
    }


def commit(db: Session, job: ImportJob, mapping: dict[str, str | None], user: User) -> dict[str, Any]:
    if job.status == "committed":
        raise ValidationFailed("This import was already committed")
    spec = spec_for(job.entity)
    rows = _validate_rows(db, job, mapping)
    cache: dict[str, Any] = {}
    counts = {"created": 0, "updated": 0, "skipped": 0}
    errors = []
    for r in rows:
        if r["errors"]:
            counts["skipped"] += 1
            errors.append({"row": r["row"], "errors": r["errors"], "values": r["values"]})
            continue
        sp = db.begin_nested()
        try:
            outcome = spec.commit_row(db, r["_typed"], user, cache)
            sp.commit()
            counts[outcome] += 1
        except Exception as exc:  # one bad row must not abort the whole import
            sp.rollback()
            cache.clear()
            counts["skipped"] += 1
            detail = getattr(exc, "detail", None) or str(exc).splitlines()[0]
            errors.append({"row": r["row"], "errors": [detail], "values": r["values"]})
    job.status = "committed"
    job.mapping = mapping
    job.result = {**counts, "errors": errors}
    audit.record(db, user, "import", job.entity, job.id, None, {"filename": job.filename, **counts})
    db.commit()
    return {"job_id": job.id, **counts, "errors": errors[:200], "error_count": len(errors)}


def error_report_csv(job: ImportJob) -> bytes:
    spec = spec_for(job.entity)
    result = job.result or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["row", *[f.name for f in spec.fields], "errors"])
    for e in result.get("errors", []):
        w.writerow([e["row"], *[e["values"].get(f.name, "") for f in spec.fields], "; ".join(e["errors"])])
    return buf.getvalue().encode("utf-8-sig")


def template(entity: str, fmt: str) -> tuple[bytes, str, str]:
    spec = spec_for(entity)
    headers = [f.name for f in spec.fields]
    example = [f.example for f in spec.fields]
    if fmt == "xlsx":
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = spec.label[:30]
        ws.append(headers)
        ws.append(example)
        for i, f in enumerate(spec.fields, start=1):
            ws.cell(row=1, column=i).font = ws.cell(row=1, column=i).font.copy(bold=True)
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, len(f.name) + 4)
        out = io.BytesIO()
        wb.save(out)
        return (
            out.getvalue(),
            f"{entity}_template.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    w.writerow(example)
    return buf.getvalue().encode("utf-8-sig"), f"{entity}_template.csv", "text/csv"
