from celery import Celery

from app.core.config import settings
from app.tasks.schedule import BEAT_SCHEDULE

celery_app = Celery(
    "smartstock", broker=settings.REDIS_URL, backend=settings.REDIS_URL, include=["app.tasks.jobs"]
)
celery_app.conf.update(
    timezone=settings.TZ,
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    worker_hijack_root_logger=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule=BEAT_SCHEDULE,
    broker_connection_retry_on_startup=True,
)
