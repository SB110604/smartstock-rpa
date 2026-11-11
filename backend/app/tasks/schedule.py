from celery.schedules import crontab

# Spec 8.7 — all times Asia/Kolkata (celery timezone is set from settings.TZ).
BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "heartbeat": {"task": "jobs.heartbeat", "schedule": 60.0},
    "approval-sla": {"task": "jobs.approval_sla", "schedule": crontab(minute="*/30")},
    "orchestrator-daily": {"task": "jobs.pipeline", "schedule": crontab(hour=6, minute=0)},
    "stock-expiry-quick-check": {"task": "jobs.quick_check", "schedule": crontab(hour="8-22/2", minute=0)},
    "tracking-hourly": {"task": "jobs.tracking", "schedule": crontab(minute=15)},
    "supplier-scores": {"task": "jobs.supplier_scores", "schedule": crontab(hour=2, minute=0)},
    "daily-summary": {"task": "jobs.daily_summary", "schedule": crontab(hour=21, minute=0)},
    "weekly-report": {"task": "jobs.weekly_report", "schedule": crontab(hour=8, minute=0, day_of_week="mon")},
    "report-schedules": {"task": "jobs.report_schedules", "schedule": crontab(hour=7, minute=0)},
    "db-backup": {"task": "jobs.backup", "schedule": crontab(hour=1, minute=0)},
    "email-quotes": {"task": "jobs.email_quotes", "schedule": crontab(minute=40)},
    "learning-daily": {"task": "jobs.learning_daily", "schedule": crontab(hour=5, minute=45)},
    "weekly-models": {"task": "jobs.weekly_models", "schedule": crontab(hour=3, minute=0, day_of_week="sun")},
}
