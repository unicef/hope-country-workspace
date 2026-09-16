import logging
from typing import Any

from streaming.manager import initialize_engine
from streaming.utils import make_event

logger = logging.getLogger(__name__)

OCR_REQUEST_ROUTING_KEY = "hd.ocr.request"


def publish(routing_key: str, payload: dict[str, Any]) -> bool:
    """Publish a payload to the streaming exchange under the given routing key.

    django-streaming keeps a process-wide engine. Celery workers reuse it across
    tasks, so a dead RabbitMQ connection can look open and fail the first
    publish. Reset and retry once when that happens.
    """
    event = make_event(payload)
    manager = initialize_engine()
    if manager.notify(routing_key, event):
        return True

    logger.warning("stream publish failed routing_key=%s; resetting engine and retrying", routing_key)
    manager = initialize_engine(True)
    return manager.notify(routing_key, event)
