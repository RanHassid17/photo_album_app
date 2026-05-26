from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "album",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.vision"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_max_tasks_per_child=50,  # Recycle workers; TF/torch leak memory over time.
    broker_connection_retry_on_startup=True,
)
