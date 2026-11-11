import time

import redis

from app.core.config import settings
from app.core.health import HEARTBEAT_KEY
from app.tasks.celery_app import celery_app


@celery_app.task(name="jobs.heartbeat")
def heartbeat() -> float:
    """Scheduled by beat, executed by a worker: proves the beat → broker → worker chain is alive."""
    now = time.time()
    redis.Redis.from_url(settings.REDIS_URL).set(HEARTBEAT_KEY, now, ex=600)
    return now


@celery_app.task(name="jobs.approval_sla")
def approval_sla() -> dict[str, int]:
    """Spec 8.1: reminders after the approval SLA, escalation to the next role after 2× SLA."""
    from app.db.session import SessionLocal
    from app.workflow import approvals

    with SessionLocal() as db:
        return approvals.check_sla(db)


@celery_app.task(name="jobs.send_email", autoretry_for=(OSError,), retry_backoff=30, max_retries=3)
def send_email(to: list[str], subject: str, html: str, text: str | None = None,
               attachments: list[tuple[str, str, str]] | None = None) -> bool:
    import base64

    from app.services import mailer

    files = [(n, base64.b64decode(d), m) for n, d, m in (attachments or [])]
    if not mailer.deliver(to, subject, html, text, files):
        raise OSError("SMTP delivery failed")
    return True


def _db():  # local import keeps the worker import graph small
    from app.db.session import SessionLocal

    return SessionLocal()


@celery_app.task(name="jobs.pipeline")
def pipeline() -> dict:
    """Daily 06:00 — full orchestrator pipeline."""
    from app.agents import orchestrator

    with _db() as db:
        return orchestrator.run_pipeline(db, "schedule")


@celery_app.task(name="jobs.quick_check")
def quick_check() -> dict:
    """Every 2 h 08:00–22:00 — stock monitor + expiry."""
    from app.agents import orchestrator

    with _db() as db:
        return orchestrator.quick_check(db)


@celery_app.task(name="jobs.tracking")
def tracking() -> dict:
    from app.agents import orchestrator

    with _db() as db:
        return orchestrator.run_agent(db, "tracking", "schedule")


@celery_app.task(name="jobs.supplier_scores")
def supplier_scores() -> int:
    """Daily 02:00 — recompute supplier scores."""
    from app.services import supplier_scoring

    with _db() as db:
        n = len(supplier_scoring.compute_scores(db))
        db.commit()
        return n


@celery_app.task(name="jobs.weekly_models")
def weekly_models() -> dict:
    """Sunday 03:00 — ABC/XYZ reclassification, anomaly-model training and forecast retraining with promotion."""
    from app.agents import orchestrator

    with _db() as db:
        return {"classify_and_anomaly": orchestrator.run_pipeline(db, "weekly", ["stock_monitor", "anomaly"]),
                "learning": orchestrator.run_agent(db, "learning", "weekly")}


@celery_app.task(name="jobs.learning_daily")
def learning_daily() -> dict:
    """05:45 — realised accuracy of yesterday's forecast + drift check (no retraining)."""
    from app.agents import orchestrator

    with _db() as db:
        return orchestrator.run_agent(db, "learning", "schedule")


@celery_app.task(name="jobs.email_quotes")
def email_quotes() -> dict:
    """Hourly — read supplier quotation emails when IMAP is configured (no-op otherwise)."""
    from app.services import quote_reader

    with _db() as db:
        return quote_reader.fetch(db)


@celery_app.task(name="jobs.daily_summary")
def daily_summary() -> int:
    """21:00 — daily summary email to managers."""
    from app.services import scheduled

    with _db() as db:
        return scheduled.daily_summary(db)


@celery_app.task(name="jobs.weekly_report")
def weekly_report() -> int:
    """Monday 08:00 — weekly report (PDF + Excel) to admins."""
    from app.services import scheduled

    with _db() as db:
        return scheduled.weekly_report(db)


@celery_app.task(name="jobs.report_schedules")
def report_schedules() -> list:
    """07:00 — user-defined report schedules that are due today."""
    from app.services import scheduled

    with _db() as db:
        return scheduled.run_due(db)


@celery_app.task(name="jobs.backup")
def backup() -> dict:
    """01:00 — pg_dump to BACKUP_DIR, keeping the newest BACKUP_KEEP archives."""
    from app.services import backup as backup_svc

    return backup_svc.create()
