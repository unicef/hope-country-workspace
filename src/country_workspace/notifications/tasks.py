import logging
from typing import Any

from django.conf import settings

from country_workspace.config.celery import app
from country_workspace.notifications.bitcaster_client import NotifyError
from country_workspace.notifications.notifier import get_notification_backend, send_notification_event

logger = logging.getLogger(__name__)


@app.task()
def send_bitcaster_event_task(event_name: str, payload: dict[str, Any]) -> None:
    """Celery task to asynchronously send an event to Bitcaster."""
    if not settings.BITCASTER_ENABLED:
        logger.info("Skipping Bitcaster task: integration disabled (event='%s').", event_name)
        return

    backend = get_notification_backend()
    if not getattr(backend, "is_configured", False):
        logger.warning("Skipping Bitcaster task: client not configured.")
        return

    try:
        success = send_notification_event(event_name, payload)
        if not success:
            logger.warning("Bitcaster client returned false for event '%s'", event_name)
    except NotifyError as exc:
        logger.error("Bitcaster send failed for event '%s': %s", event_name, str(exc))
