"""Supplier-invoice OCR (spec 6.5): Tesseract text → line parsing (regex; LLM JSON when enabled) → RapidFuzz product
matching with per-line confidence. The result only pre-fills a form; nothing is saved without user confirmation."""

import io
import json
import logging
import re
from datetime import date, datetime
from typing import Any

from PIL import Image, ImageOps
from rapidfuzz import fuzz, process, utils
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import llm
from app.core.config import settings as env
from app.core.errors import AppError, ValidationFailed
from app.core.logging import log_ctx
from app.models.catalog import Product, Supplier
from app.models.purchasing import PurchaseOrder

logger = logging.getLogger("app.ocr")

NUM = r"\d+(?:,\d{2,3})*(?:\.\d{1,2})?"
LINE_RE = re.compile(
    rf"^\s*(?:\d{{1,3}}[.)]?\s+)?(?P<desc>[A-Za-z][A-Za-z0-9&'()/.,%\- ]{{2,}}?)\s+(?:(?P<hsn>\d{{4,8}})\s+)?"
    rf"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z]{{1,6}})?\s+(?:x\s*)?(?:Rs\.?|₹)?\s*(?P<rate>{NUM})\s+"
    rf"(?:(?P<gst>\d{{1,2}})\s*%\s+)?(?:Rs\.?|₹)?\s*(?P<amount>{NUM})\s*$", re.I)
INVOICE_NO_RE = re.compile(r"(?:invoice|bill|inv)\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{2,30})", re.I)
DATE_RE = re.compile(r"(\d{1,2})[\-/.](\d{1,2})[\-/.](\d{2,4})")
GSTIN_RE = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z])\b")
TOTAL_RE = re.compile(rf"(?:grand\s*total|total\s*amount|net\s*amount|total)\s*[:\-]?\s*(?:Rs\.?|₹)?\s*({NUM})", re.I)
SKIP_RE = re.compile(r"\b(total|subtotal|sub total|cgst|sgst|igst|tax|amount in words|round|gstin|invoice|date)\b", re.I)


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def available() -> bool:
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = env.TESSERACT_CMD
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def extract_text(content: bytes, filename: str) -> str:
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = env.TESSERACT_CMD
    name = filename.lower()
    if name.endswith(".pdf"):
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(content, dpi=300)
    elif name.endswith((".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")):
        images = [Image.open(io.BytesIO(content))]
    else:
        raise ValidationFailed("Upload a JPG, PNG or PDF invoice")
    out = []
    for img in images:
        g = ImageOps.grayscale(ImageOps.exif_transpose(img))
        if g.width < 1600:  # small phone photos OCR better when upscaled
            g = g.resize((g.width * 2, g.height * 2))
        out.append(pytesseract.image_to_string(g, config="--psm 6"))
    return "\n".join(out)


def parse_text(text: str) -> dict[str, Any]:
    """Rule-based extraction of header fields and line items."""
    inv = INVOICE_NO_RE.search(text)
    gst = GSTIN_RE.findall(text.replace(" ", "")) or GSTIN_RE.findall(text)
    d = None
    for m in DATE_RE.finditer(text):
        dd, mm, yy = (int(x) for x in m.groups())
        yy = yy + 2000 if yy < 100 else yy
        try:
            d = date(yy, mm, dd)
            break
        except ValueError:
            continue
    totals = [_num(m.group(1)) for m in TOTAL_RE.finditer(text)]
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or SKIP_RE.search(line):
            continue
        m = LINE_RE.match(line)
        if not m:
            continue
        qty, rate, amount = _num(m.group("qty")), _num(m.group("rate")), _num(m.group("amount"))
        if not qty or rate is None or amount is None:
            continue
        arithmetic_ok = abs(qty * rate - amount) <= max(1.0, 0.02 * amount)
        lines.append({"description": m.group("desc").strip(" .-"), "hsn": m.group("hsn"), "qty": qty, "unit": m.group("unit"),
                      "unit_price": rate, "amount": amount, "gst_rate": _num(m.group("gst")), "arithmetic_ok": arithmetic_ok})
    return {"invoice_no": inv.group(1) if inv else None, "invoice_date": d.isoformat() if d else None,
            "gstins": gst, "total": max((t for t in totals if t), default=None), "lines": lines, "method": "rules"}


def parse_with_llm(text: str) -> dict[str, Any] | None:
    provider = llm.get_provider()
    if provider is None:
        return None
    try:
        reply = provider.chat(
            "Extract supplier invoice data. Reply with JSON only: {\"invoice_no\": str|null, \"invoice_date\": \"YYYY-MM-DD\"|null, "
            "\"gstin\": str|null, \"total\": number|null, \"lines\": [{\"description\": str, \"qty\": number, \"unit_price\": number, "
            "\"gst_rate\": number|null}]}. Use numbers exactly as printed.",
            [{"role": "user", "content": text[:6000]}])
        raw = reply.text[reply.text.find("{"): reply.text.rfind("}") + 1]
        data = json.loads(raw)
        lines = [{"description": str(x["description"]), "qty": float(x["qty"]), "unit_price": float(x["unit_price"]),
                  "amount": round(float(x["qty"]) * float(x["unit_price"]), 2), "gst_rate": x.get("gst_rate"),
                  "hsn": None, "unit": None, "arithmetic_ok": True} for x in data.get("lines", [])]
        if not lines:
            return None
        return {"invoice_no": data.get("invoice_no"), "invoice_date": data.get("invoice_date"),
                "gstins": [data["gstin"]] if data.get("gstin") else [], "total": data.get("total"), "lines": lines,
                "method": provider.name}
    except (llm.LLMError, ValueError, KeyError, TypeError) as exc:
        logger.warning("llm invoice extraction failed, using rules", extra=log_ctx(error=str(exc)))
        return None


def match(db: Session, parsed: dict[str, Any], text: str, po_id: int | None = None) -> dict[str, Any]:
    products = list(db.scalars(select(Product).where(Product.is_active.is_(True))).unique())
    names = {p.id: p.name for p in products}
    by_id = {p.id: p for p in products}
    suppliers = list(db.scalars(select(Supplier)))
    supplier = None
    for g in parsed.get("gstins") or []:
        supplier = next((s for s in suppliers if s.gstin and s.gstin == g), None)
        if supplier:
            break
    if supplier is None and suppliers:
        best = process.extractOne(text[:600], {s.id: s.name for s in suppliers}, scorer=fuzz.partial_ratio,
                                  processor=utils.default_process)
        if best and best[1] >= 85:
            supplier = next(s for s in suppliers if s.id == best[2])
    po = db.get(PurchaseOrder, po_id) if po_id else None
    po_lines = {ln.product_id: ln for ln in po.lines} if po else {}
    out = []
    for ln in parsed["lines"]:
        hit = process.extractOne(ln["description"], names, scorer=fuzz.WRatio, processor=utils.default_process) if names else None
        score = float(hit[1]) if hit else 0.0
        pid = int(hit[2]) if hit and score >= 60 else None
        if po_lines and pid not in po_lines and hit:  # prefer an item that is on this PO
            on_po = process.extractOne(ln["description"], {k: names[k] for k in po_lines}, scorer=fuzz.WRatio,
                                       processor=utils.default_process)
            if on_po and on_po[1] >= score - 10:
                pid, score = int(on_po[2]), float(on_po[1])
        confidence = round(0.65 * score + 0.35 * (100 if ln.get("arithmetic_ok") else 50), 1)
        pl = po_lines.get(pid) if pid else None
        out.append({**ln, "product_id": pid, "product_name": by_id[pid].name if pid else None, "match_score": round(score, 1),
                    "confidence": confidence, "po_line_id": pl.id if pl else None,
                    "gst_rate": ln.get("gst_rate") if ln.get("gst_rate") is not None else (by_id[pid].gst_rate if pid else None)})
    open_pos = []
    if supplier and not po:
        open_pos = [{"id": p.id, "po_no": p.po_no, "status": p.status, "total": p.total}
                    for p in db.scalars(select(PurchaseOrder).where(PurchaseOrder.supplier_id == supplier.id,
                                                                    PurchaseOrder.status.in_(("DISPATCHED", "PARTIALLY_RECEIVED",
                                                                                              "RECEIVED", "CONFIRMED", "SENT"))))]
    return {"invoice_no": parsed.get("invoice_no"), "invoice_date": parsed.get("invoice_date") or date.today().isoformat(),
            "supplier": {"id": supplier.id, "name": supplier.name} if supplier else None, "total": parsed.get("total"),
            "lines": out, "method": parsed.get("method"), "candidate_pos": open_pos,
            "overall_confidence": round(sum(x["confidence"] for x in out) / len(out), 1) if out else 0.0}


def scan_invoice(db: Session, content: bytes, filename: str, po_id: int | None = None) -> dict[str, Any]:
    if not available():
        raise AppError("OCR engine (Tesseract) is not installed on the server — enter the invoice manually.",
                       code="ocr_unavailable", status_code=503)
    started = datetime.now()
    text = extract_text(content, filename)
    parsed = parse_with_llm(text) or parse_text(text)
    if not parsed["lines"]:
        parsed_rules = parse_text(text)
        parsed = parsed_rules if parsed_rules["lines"] else parsed
    result = match(db, parsed, text, po_id)
    result["text"] = text
    result["seconds"] = round((datetime.now() - started).total_seconds(), 2)
    return result
