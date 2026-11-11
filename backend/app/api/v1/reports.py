"""Dashboards, reports (JSON / PDF / Excel), report schedules and database backups."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.api.v1.portal import summary as portal_summary
from app.core.deps import DB, CurrentUser, require
from app.core.errors import Forbidden, ValidationFailed
from app.core.permissions import allowed
from app.models.core import ReportSchedule, Role, User
from app.services import audit, backup, dashboard, reports, scheduled

router = APIRouter(tags=["reports"])
Reporter = Annotated[User, Depends(require("reports.read"))]
Admin = Annotated[User, Depends(require("settings.manage"))]


@router.get("/dashboard")
def get_dashboard(user: CurrentUser, db: DB) -> dict[str, Any]:
    """Role-based dashboard: management (admin/manager), staff tasks, or the supplier's portal summary."""
    if user.role == Role.SUPPLIER:
        return {"role": "supplier", "supplier": portal_summary(user, db)}
    if user.role == Role.STAFF:
        return {"role": "staff", "staff": dashboard.staff(db)}
    return {"role": user.role, **dashboard.management(db, user)}


@router.get("/reports")
def list_reports(user: Reporter) -> list[dict[str, str]]:
    return [{"name": k, "title": v[0]} for k, v in reports.REPORTS.items()]


@router.get("/reports/{name}", response_model=None)
def get_report(name: str, user: Reporter, db: DB, date_from: date | None = None, date_to: date | None = None,
               location_id: int | None = None, fmt: str = "json") -> dict[str, Any] | Response:
    r = reports.build(db, name, date_from, date_to, location_id)
    stamp = f"{r.date_to or date.today():%Y%m%d}"
    if fmt == "pdf":
        return Response(reports.to_pdf(db, r), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}_{stamp}.pdf"'})
    if fmt == "xlsx":
        return Response(reports.to_xlsx(r), media_type=scheduled.XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{name}_{stamp}.xlsx"'})
    return reports.to_json(r)


class ScheduleIn(BaseModel):
    report: str
    frequency: str = Field(pattern="^(daily|weekly|monthly)$")
    recipients: list[EmailStr] = Field(min_length=1, max_length=20)
    fmt: str = Field("pdf", pattern="^(pdf|xlsx|both)$")
    is_active: bool = True


def schedule_out(s: ReportSchedule) -> dict[str, Any]:
    return {"id": s.id, "report": s.report, "frequency": s.frequency, "recipients": s.recipients, "fmt": s.fmt,
            "is_active": s.is_active, "last_sent_at": s.last_sent_at}


@router.get("/report-schedules")
def list_schedules(user: Reporter, db: DB) -> list[dict[str, Any]]:
    return [schedule_out(s) for s in db.scalars(select(ReportSchedule).order_by(ReportSchedule.id))]


@router.post("/report-schedules", status_code=201)
def create_schedule(body: ScheduleIn, user: Reporter, db: DB) -> dict[str, Any]:
    if body.report not in reports.REPORTS:
        raise ValidationFailed("Unknown report")
    s = ReportSchedule(**body.model_dump(), created_by=user.id)
    db.add(s)
    audit.created(db, user, s)
    db.commit()
    return schedule_out(s)


@router.put("/report-schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: ScheduleIn, user: Reporter, db: DB) -> dict[str, Any]:
    s = scheduled.get_schedule(db, schedule_id)
    audit.apply_update(db, user, s, body.model_dump())
    db.commit()
    return schedule_out(s)


@router.delete("/report-schedules/{schedule_id}")
def delete_schedule(schedule_id: int, user: Reporter, db: DB) -> dict[str, str]:
    s = scheduled.get_schedule(db, schedule_id)
    audit.deleted(db, user, s)
    db.delete(s)
    db.commit()
    return {"detail": "Schedule deleted"}


@router.post("/report-schedules/{schedule_id}/send")
def send_schedule(schedule_id: int, user: Reporter, db: DB) -> dict[str, Any]:
    return scheduled.send_schedule(db, scheduled.get_schedule(db, schedule_id))


# ---------------------------------------------------------------- backups (admin)

class RestoreIn(BaseModel):
    confirm: str


@router.get("/backups")
def list_backups(user: Admin) -> list[dict[str, Any]]:
    return backup.list_all()


@router.post("/backups", status_code=201)
def create_backup(user: Admin, db: DB) -> dict[str, Any]:
    info = backup.create()
    audit.record(db, user, "backup", "database", info["name"])
    db.commit()
    return info


@router.get("/backups/{name}")
def download_backup(name: str, user: Admin) -> FileResponse:
    return FileResponse(backup.path(name), filename=name, media_type="application/octet-stream")


@router.post("/backups/{name}/restore")
def restore_backup(name: str, body: RestoreIn, user: Admin, db: DB) -> dict[str, Any]:
    if body.confirm != "RESTORE":
        raise ValidationFailed("Type RESTORE to confirm — this replaces all current data")
    if not allowed(user.role, "settings.manage"):
        raise Forbidden("Admins only")
    db.close()  # release our connection before the restore drops and recreates objects
    return backup.restore(name)
