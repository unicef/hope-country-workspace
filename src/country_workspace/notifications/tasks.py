import logging
from typing import Any

import requests

from country_workspace.config.celery import app
from country_workspace.notifications.bitcaster_client import RetryableBitcasterError
from country_workspace.notifications.notifier import get_notification_backend, send_notification_event

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=3)
def send_bitcaster_event_task(self: Any, event_name: str, payload: dict[str, Any]) -> None:
    """Celery task to asynchronously send an event to Bitcaster."""
    backend = get_notification_backend()
    if not getattr(backend, "is_configured", False):
        logger.warning("Skipping Bitcaster task: client not configured.")
        return

    try:
        success = send_notification_event(event_name, payload)
        if not success:
            logger.warning("Bitcaster client returned false for event '%s'", event_name)
    except RetryableBitcasterError as exc:
        logger.warning("Retryable Bitcaster error for event '%s': %s", event_name, str(exc))
        self.retry(exc=exc, countdown=2**self.request.retries * 5)
    except requests.exceptions.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error(
            "Non-retryable Bitcaster HTTP error for event '%s' (status=%s): %s",
            event_name,
            status_code,
            str(exc),
        )
