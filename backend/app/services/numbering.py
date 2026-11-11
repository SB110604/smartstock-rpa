"""Human-readable document numbers such as PO-202611-0001 (sequence restarts each month)."""

import zlib
from datetime import date

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute


def next_number(db: Session, column: InstrumentedAttribute[str], prefix: str, on: date | None = None) -> str:
    day = on or date.today()
    stem = f"{prefix}-{day:%Y%m}-"
    # Serialise number allocation per prefix inside this transaction (released on commit/rollback).
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": zlib.crc32(stem.encode())})
    last = db.scalar(select(func.max(column)).where(column.like(f"{stem}%")))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{stem}{seq:04d}"
