"""Sales / billing. Prices are GST-inclusive (Indian retail MRP convention); tax is backed out per line."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ValidationFailed
from app.core.timeutil import now
from app.models.core import User
from app.models.inventory import MovementType, Sale, SaleLine
from app.services import audit, numbering, stock


def create_sale(
    db: Session,
    *,
    location_id: int,
    lines: list[dict[str, Any]],
    channel: str,
    user: User | None,
    invoice_no: str | None = None,
    sold_at: datetime | None = None,
    customer_name: str | None = None,
    commit: bool = True,
) -> Sale:
    if not lines:
        raise ValidationFailed("A sale needs at least one line")
    stock.check_location(db, location_id)
    if invoice_no and db.scalar(select(Sale.id).where(Sale.invoice_no == invoice_no)):
        raise Conflict(f"Invoice {invoice_no} already recorded", code="duplicate_invoice")
    at = sold_at or now()
    sale = Sale(
        invoice_no=invoice_no or numbering.next_number(db, Sale.invoice_no, "INV", at.date()),
        location_id=location_id,
        sold_at=at,
        channel=channel,
        customer_name=customer_name,
        user_id=user.id if user else None,
    )
    db.add(sale)
    db.flush()
    subtotal = tax = 0.0
    for line in lines:
        product = stock.get_product(db, int(line["product_id"]))
        if not product.is_active:
            raise ValidationFailed(f"{product.name} is inactive and cannot be sold")
        qty = float(line["qty"])
        discount = float(line.get("discount_pct") or 0)
        picks = stock.issue(
            db,
            product=product,
            location_id=location_id,
            qty=qty,
            movement_type=MovementType.SALE_OUT,
            user=user,
            ref_type="sale",
            ref_id=sale.id,
            at=at,
        )
        for batch, take in picks:
            base = line.get("unit_price")
            price = (
                float(base) if base is not None else product.selling_price * (1 - batch.markdown_pct / 100)
            )
            total = round(take * price * (1 - discount / 100), 2)
            line_tax = round(total * product.gst_rate / (100 + product.gst_rate), 2)
            sale.lines.append(
                SaleLine(
                    product_id=product.id,
                    batch_id=batch.id,
                    qty=take,
                    unit_price=round(price, 2),
                    discount_pct=discount,
                    gst_rate=product.gst_rate,
                    line_total=total,
                )
            )
            subtotal += total - line_tax
            tax += line_tax
    sale.subtotal = round(subtotal, 2)
    sale.tax = round(tax, 2)
    sale.total = round(subtotal + tax, 2)
    db.flush()
    audit.record(
        db,
        user,
        "create",
        "sales",
        sale.id,
        None,
        {"invoice_no": sale.invoice_no, "total": sale.total, "lines": len(sale.lines), "channel": channel},
    )
    if commit:
        db.commit()
    return sale
