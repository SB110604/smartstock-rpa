"""Scheduled emails (spec 8.7): daily summary to managers, weekly report pack to admins, user report schedules."""

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.errors import NotFound
from app.core.timeutil import now, start_of_day, today
from app.models.ai import Alert
from app.models.core import ReportSchedule, Role
from app.models.inventory import Sale
from app.services import dashboard, mailer, notify, reports
from app.services import settings as settings_svc
from app.services.pdfbase import inr

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def attachments(db: Session, r: reports.Report, fmt: str) -> list[tuple[str, bytes, str]]:
    stamp = f"{r.date_to or today():%Y%m%d}"
    out = []
    if fmt in ("pdf", "both"):
        out.append((f"{r.name}_{stamp}.pdf", reports.to_pdf(db, r), "application/pdf"))
    if fmt in ("xlsx", "both"):
        out.append((f"{r.name}_{stamp}.xlsx", reports.to_xlsx(r), XLSX))
    return out


def daily_summary(db: Session) -> int:
    """21:00 — the day in numbers for managers."""
    business = settings_svc.get(db, "business")["name"]
    k = dashboard.kpis(db)
    t0 = start_of_day(today())
    revenue, bills = db.execute(select(func.coalesce(func.sum(Sale.total), 0), func.count()).where(Sale.sold_at >= t0)).one()
    crit = db.scalar(select(func.count()).select_from(Alert).where(Alert.status == "open", Alert.severity == "critical")) or 0
    rows = [("Sales today", f"{inr(float(revenue))} from {bills} bills"), ("Stock value", inr(k["stock_value"])),
            ("Below reorder point", k["below_rop"]), ("Out of stock", k["out_of_stock"]),
            ("Near-expiry stock (30 days)", inr(k["near_expiry_value"])), ("Pending approvals", k["pending_approvals"]),
            ("Open purchase orders", f"{k['open_pos']} ({k['late_deliveries']} late)"), ("Critical alerts", crit)]
    table = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#475569'>{a}</td><td><b>{b}</b></td></tr>" for a, b in rows)
    html = mailer.layout(f"Daily summary — {today():%d-%m-%Y}", f"<table>{table}</table>"
                         + mailer.button(f"{env.FRONTEND_URL}/", "Open dashboard"), business)
    users = notify.users_with_roles(db, [Role.MANAGER])
    for u in users:
        mailer.send_email(u.email, f"{business}: daily summary {today():%d-%m-%Y}", html)
    return len(users)


def weekly_report(db: Session) -> int:
    """Monday 08:00 — last week's sales, purchases and stock valuation (PDF + Excel) to admins."""
    business = settings_svc.get(db, "business")["name"]
    d2, d1 = today() - timedelta(days=1), today() - timedelta(days=7)
    files: list[tuple[str, bytes, str]] = []
    lines = []
    for name in ("sales", "purchases", "stock_valuation"):
        r = reports.build(db, name, d1, d2)
        files += attachments(db, r, "both")
        lines.append(f"<li><b>{r.title}</b>: " + ", ".join(f"{a} {b}" for a, b in r.summary) + "</li>")
    html = mailer.layout(f"Weekly report {d1:%d-%m-%Y} – {d2:%d-%m-%Y}", f"<ul>{''.join(lines)}</ul><p>PDF and Excel attached.</p>",
                         business)
    users = notify.users_with_roles(db, [Role.ADMIN])
    for u in users:
        mailer.send_email(u.email, f"{business}: weekly report", html, attachments=files)
    return len(users)


def send_schedule(db: Session, s: ReportSchedule) -> dict[str, Any]:
    d1, d2 = reports.period_for(s.frequency)
    r = reports.build(db, s.report, d1, d2)
    business = settings_svc.get(db, "business")["name"]
    html = mailer.layout(r.title, "".join(f"<p>{a}: <b>{b}</b></p>" for a, b in r.summary) + "<p>Report attached.</p>", business)
    sent = sum(1 for to in s.recipients if mailer.send_email(to, f"{business}: {r.title}", html, attachments=attachments(db, r, s.fmt)))
    s.last_sent_at = now()
    db.commit()
    return {"schedule_id": s.id, "sent": sent}


def due(s: ReportSchedule) -> bool:
    t = today()
    if s.last_sent_at and s.last_sent_at.date() == t:
        return False
    return s.frequency == "daily" or (s.frequency == "weekly" and t.weekday() == 0) or (s.frequency == "monthly" and t.day == 1)


def run_due(db: Session) -> list[dict[str, Any]]:
    return [send_schedule(db, s) for s in db.scalars(select(ReportSchedule).where(ReportSchedule.is_active.is_(True))) if due(s)]


def get_schedule(db: Session, schedule_id: int) -> ReportSchedule:
    s = db.get(ReportSchedule, schedule_id)
    if not s:
        raise NotFound("Schedule not found")
    return s
