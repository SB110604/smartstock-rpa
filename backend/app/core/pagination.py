from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = 1
    page_size: int = 25
    sort: str | None = None


def page_params(
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500), sort: str | None = None
) -> PageParams:
    return PageParams(page=page, page_size=page_size, sort=sort)


def apply_sort(stmt: Select[Any], sort: str | None, allowed: dict[str, Any], default: Any) -> Select[Any]:
    """`sort=name` ascending, `sort=-name` descending; only whitelisted columns are sortable."""
    if sort:
        desc = sort.startswith("-")
        col = allowed.get(sort.lstrip("-"))
        if col is not None:
            return stmt.order_by(col.desc().nulls_last() if desc else col.asc().nulls_last())
    return stmt.order_by(default)


def paginate(
    db: Session, stmt: Select[Any], params: PageParams, transform: Callable[[Any], Any] | None = None
) -> dict[str, Any]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = db.execute(stmt.limit(params.page_size).offset((params.page - 1) * params.page_size))
    single_entity = len(stmt.column_descriptions) == 1
    items = list(rows.scalars().unique()) if single_entity else list(rows.all())
    if transform:
        items = [transform(i) for i in items]
    return {"items": items, "total": total, "page": params.page, "page_size": params.page_size}
