"""Email quotation reader (spec 6.7). When IMAP is configured, unread supplier emails are parsed for price updates
that land in supplier_quotes as `pending_review`. Without IMAP settings the feature is hidden."""

import email
import imaplib
import logging
import re
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any

from rapidfuzz import fuzz, process, utils
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.logging import log_ctx
from app.models.catalog import Product, Supplier
from app.models.purchasing import SupplierQuote

logger = logging.getLogger("app.quotes")
PRICE_LINE = re.compile(r"^\s*[-*•]?\s*(?P<item>[A-Za-z][A-Za-z0-9 &'()/.\-]{2,60}?)\s*[:\-–=@]\s*(?:Rs\.?|₹|INR)?\s*"
                        r"(?P<price>\d+(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:/|per)?\s*(?P<unit>[A-Za-z]{0,8})"
                        r"(?:.*?(?:lead|delivery)\D{0,12}(?P<lead>\d{1,2})\s*days?)?", re.I)


def parse_quote_text(db: Session, body: str) -> list[dict[str, Any]]:
    products = {p.id: p.name for p in db.scalars(select(Product).where(Product.is_active.is_(True)))}
    out = []
    for line in body.splitlines():
        m = PRICE_LINE.match(line)
        if not m:
            continue
        hit = process.extractOne(m.group("item"), products, scorer=fuzz.WRatio, processor=utils.default_process)
        if not hit or hit[1] < 75:
            continue
        out.append({"product_id": int(hit[2]), "product": hit[0], "match_score": round(hit[1], 1),
                    "unit_price": float(m.group("price").replace(",", "")),
                    "lead_time_days": int(m.group("lead")) if m.group("lead") else None, "line": line.strip()})
    return out


def ingest(db: Session, from_addr: str, subject: str, body: str) -> list[SupplierQuote]:
    supplier = db.scalar(select(Supplier).where(func.lower(Supplier.email) == from_addr.lower()))
    if not supplier:
        logger.info("quote email from unknown sender ignored", extra=log_ctx(sender=from_addr))
        return []
    quotes = []
    for q in parse_quote_text(db, body):
        sq = SupplierQuote(supplier_id=supplier.id, product_id=q["product_id"], unit_price=q["unit_price"],
                           lead_time_days=q["lead_time_days"], status="pending_review", source="email",
                           note=f"{subject[:120]} — “{q['line'][:200]}” (match {q['match_score']}%)")
        db.add(sq)
        quotes.append(sq)
    db.flush()
    return quotes


def _body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")


def fetch(db: Session) -> dict[str, int]:
    if not env.imap_enabled:
        return {"skipped": 1}
    created = read = 0
    with imaplib.IMAP4_SSL(env.IMAP_HOST, env.IMAP_PORT) as imap:
        imap.login(env.IMAP_USER, env.IMAP_PASSWORD)
        imap.select(env.IMAP_FOLDER)
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, raw = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(raw[0][1])  # type: ignore[index]
            read += 1
            subject = str(make_header(decode_header(msg.get("Subject", ""))))
            created += len(ingest(db, parseaddr(msg.get("From", ""))[1], subject, _body(msg)))
    db.commit()
    return {"emails": read, "quotes": created}
