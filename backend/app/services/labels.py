"""Printable barcode label sheets: A4, 3 × 8 labels, each with a Code128 barcode and a QR code (spec 6.3)."""

import io
from dataclasses import dataclass

import barcode
import qrcode
from barcode.writer import ImageWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.pdfbase import fonts, inr

COLS, ROWS = 3, 8
LABEL_W, LABEL_H = 70 * mm, 37 * mm
MARGIN_X = (A4[0] - COLS * LABEL_W) / 2
MARGIN_Y = (A4[1] - ROWS * LABEL_H) / 2


@dataclass
class Label:
    title: str
    code: str  # encoded in Code128 (barcode or SKU)
    qr: str  # QR payload: "SKU" for products, "SKU|BATCHNO" for batches (understood by the scanner)
    line1: str
    line2: str = ""


def _code128_png(value: str) -> ImageReader:
    out = io.BytesIO()
    barcode.get("code128", value, writer=ImageWriter()).write(
        out,
        options={
            "module_height": 9.0,
            "module_width": 0.25,
            "quiet_zone": 1.5,
            "write_text": False,
            "dpi": 300,
        },
    )
    out.seek(0)
    return ImageReader(out)


def _qr_png(value: str) -> ImageReader:
    img = qrcode.make(value, box_size=6, border=1)
    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return ImageReader(out)


def render(labels: list[Label]) -> bytes:
    regular, bold = fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("SmartStock labels")
    per_page = COLS * ROWS
    for i, lb in enumerate(labels):
        if i and i % per_page == 0:
            c.showPage()
        slot = i % per_page
        col, row = slot % COLS, slot // COLS
        x = MARGIN_X + col * LABEL_W
        y = A4[1] - MARGIN_Y - (row + 1) * LABEL_H
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setDash(1, 2)
        c.rect(x, y, LABEL_W, LABEL_H)
        c.setDash()
        pad = 3 * mm
        c.setFont(bold, 8)
        title = lb.title if len(lb.title) <= 34 else lb.title[:33] + "…"
        c.drawString(x + pad, y + LABEL_H - pad - 6, title)
        c.setFont(regular, 7)
        c.drawString(x + pad, y + LABEL_H - pad - 15, lb.line1)
        if lb.line2:
            c.drawString(x + pad, y + LABEL_H - pad - 23, lb.line2)
        qr_size = 20 * mm
        c.drawImage(_qr_png(lb.qr), x + LABEL_W - pad - qr_size, y + pad, qr_size, qr_size)
        c.drawImage(
            _code128_png(lb.code),
            x + pad,
            y + pad + 4,
            LABEL_W - qr_size - 3 * pad,
            10 * mm,
            preserveAspectRatio=False,
        )
        c.setFont(regular, 6.5)
        c.drawString(x + pad, y + pad - 1, lb.code)
    c.save()
    return buf.getvalue()


def product_label(name: str, sku: str, barcode_value: str | None, price: float, unit: str) -> Label:
    return Label(
        title=name, code=barcode_value or sku, qr=sku, line1=f"SKU {sku}", line2=f"{inr(price)} / {unit}"
    )


def batch_label(name: str, sku: str, batch_no: str, expiry: str | None) -> Label:
    return Label(
        title=name,
        code=sku,
        qr=f"{sku}|{batch_no}",
        line1=f"Batch {batch_no}",
        line2=f"Expiry {expiry}" if expiry else "No expiry",
    )
