import logging
from typing import Any
from django.dispatch import receiver

from country_workspace.notifications.signals import (
    data_imported_signal,
    validation_completed_signal,
    rdi_pushed_signal,
    rdp_pushed_signal,
)
from country_workspace.notifications.tasks import send_bitcaster_event_task

logger = logging.getLogger(__name__)


@receiver(data_imported_signal)
def handle_data_imported(sender: Any, **kwargs: Any) -> None:
    # Build a standard payload dictionary using kwargs
    payload = {
        "program_id": kwargs.get("program_id"),
        "batch_id": kwargs.get("batch_id"),
        "record_count": kwargs.get("record_count"),
        "source": kwargs.get("source"),
    }
    # Queue the Celery task
    send_bitcaster_event_task.delay("data_imported", payload)


@receiver(validation_completed_signal)
def handle_validation_completed(sender: Any, **kwargs: Any) -> None:
    payload = {
        "program_id": kwargs.get("program_id"),
        "context": kwargs.get("context"),
        "results": kwargs.get("results", {}),
    }
    send_bitcaster_event_task.delay("validation_completed", payload)


@receiver(rdi_pushed_signal)
def handle_rdi_pushed(sender: Any, **kwargs: Any) -> None:
    payload = {
        "program_id": kwargs.get("program_id"),
        "target": kwargs.get("target"),
        "pushed_count": kwargs.get("pushed_count"),
    }
    send_bitcaster_event_task.delay("rdi_pushed", payload)


@receiver(rdp_pushed_signal)
def handle_rdp_pushed(sender: Any, **kwargs: Any) -> None:
    payload = {
        "program_id": kwargs.get("program_id"),
        "rdp_id": kwargs.get("rdp_id"),
        "status": kwargs.get("status"),
    }
    send_bitcaster_event_task.delay("rdp_pushed", payload)
