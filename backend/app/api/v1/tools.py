"""Audit log viewer, import center and barcode label printing."""

from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import DB, require
from app.core.errors import ValidationFailed
from app.core.pagination import PageParams, page_params, paginate
from app.core.timeutil import start_of_day
from app.models.catalog import Product
from app.models.core import AuditLog, User
from app.models.inventory import Batch
from app.services import imports, labels

router = APIRouter(tags=["tools"])
Auditor = Annotated[User, Depends(require("audit.read"))]
Importer = Annotated[User, Depends(require("imports.run"))]
Printer = Annotated[User, Depends(require("labels.print"))]

MAX_UPLOAD = 10 * 1024 * 1024


@router.get("/audit")
def audit_log(
    user: Auditor,
    db: DB,
    p: Annotated[PageParams, Depends(page_params)],
    entity: str | None = None,
    action: str | None = None,
    user_id: int | None = None,
    entity_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    stmt = select(AuditLog, User.name).outerjoin(User, User.id == AuditLog.user_id)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= start_of_day(date_from))
    if date_to:
        stmt = stmt.where(AuditLog.created_at < start_of_day(date_to + timedelta(days=1)))
    page = paginate(db, stmt.order_by(AuditLog.id.desc()), p)
    page["items"] = [
        {
            "id": a.id,
            "user_id": a.user_id,
            "user_name": name,
            "action": a.action,
            "entity": a.entity,
            "entity_id": a.entity_id,
            "before": a.before_json,
            "after": a.after_json,
            "ip": a.ip,
            "created_at": a.created_at,
        }
        for a, name in page["items"]
    ]
    return page


@router.get("/audit/entities")
def audit_entities(user: Auditor, db: DB) -> list[str]:
    return sorted(e for (e,) in db.execute(select(AuditLog.entity).distinct()))


# ------------------------------------------------------------------ imports


class MappingIn(BaseModel):
    mapping: dict[str, str | None]


@router.get("/imports/types")
def import_types(user: Importer) -> list[dict[str, Any]]:
    return imports.describe()


@router.get("/imports/templates/{entity}")
def import_template(entity: str, user: Importer, fmt: str = "csv") -> Response:
    data, filename, mime = imports.template(entity, "xlsx" if fmt == "xlsx" else "csv")
    return Response(
        data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.post("/imports/upload", status_code=201)
async def import_upload(
    user: Importer, db: DB, entity: Annotated[str, Form()], file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    content = await file.read()
    if len(content) > MAX_UPLOAD:
        raise ValidationFailed("File is larger than 10 MB")
    job = imports.upload(db, entity, file.filename or "upload.csv", content, user)
    spec = imports.spec_for(entity)
    return {
        "job_id": job.id,
        "entity": entity,
        "filename": job.filename,
        "columns": job.columns,
        "rows": len(job.rows),
        "sample": job.rows[:5],
        "mapping": job.mapping,
        "fields": [{"name": f.name, "type": f.type, "required": f.required} for f in spec.fields],
    }


@router.post("/imports/{job_id}/preview")
def import_preview(job_id: int, body: MappingIn, user: Importer, db: DB) -> dict[str, Any]:
    return imports.preview(db, imports.get_job(db, job_id, user), body.mapping)


@router.post("/imports/{job_id}/commit")
def import_commit(job_id: int, body: MappingIn, user: Importer, db: DB) -> dict[str, Any]:
    return imports.commit(db, imports.get_job(db, job_id, user), body.mapping, user)


@router.get("/imports/{job_id}/errors.csv")
def import_errors(job_id: int, user: Importer, db: DB) -> Response:
    job = imports.get_job(db, job_id, user)
    return Response(
        imports.error_report_csv(job),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="import_{job_id}_errors.csv"'},
    )


# ------------------------------------------------------------------ labels


class ProductLabelsIn(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=500)
    copies: int = Field(1, ge=1, le=48)


class BatchLabelsIn(BaseModel):
    batch_ids: list[int] = Field(min_length=1, max_length=500)
    copies: int = Field(1, ge=1, le=48)


def _pdf(data: bytes, name: str) -> Response:
    return Response(
        data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'}
    )


@router.post("/labels/products")
def product_labels(body: ProductLabelsIn, user: Printer, db: DB) -> Response:
    products = list(
        db.scalars(select(Product).where(Product.id.in_(body.product_ids)).order_by(Product.name)).unique()
    )
    if not products:
        raise ValidationFailed("No products selected")
    items = [
        labels.product_label(p.name, p.sku, p.barcode, p.selling_price, p.unit)
        for p in products
        for _ in range(body.copies)
    ]
    return _pdf(labels.render(items), "product_labels.pdf")


@router.post("/labels/batches")
def batch_labels(body: BatchLabelsIn, user: Printer, db: DB) -> Response:
    batches = list(db.scalars(select(Batch).where(Batch.id.in_(body.batch_ids))).unique())
    if not batches:
        raise ValidationFailed("No batches selected")
    items = [
        labels.batch_label(
            b.product.name,
            b.product.sku,
            b.batch_no,
            b.expiry_date.strftime("%d-%m-%Y") if b.expiry_date else None,
        )
        for b in batches
        for _ in range(body.copies)
    ]
    return _pdf(labels.render(items), "batch_labels.pdf")
