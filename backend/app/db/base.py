from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, MetaData, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Quantities and money are stored as exact NUMERIC in Postgres but surface as Python floats, so
# ML/statistics code and business code share one numeric type. Money is rounded to 2 dp in services.
NUM = Numeric(14, 3, asdecimal=False)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        date: Date(),
        float: NUM,
        str: String(255),
        dict[str, Any]: JSONType,
        list[Any]: JSONType,
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class IdMixin:
    id: Mapped[int] = mapped_column(primary_key=True)
