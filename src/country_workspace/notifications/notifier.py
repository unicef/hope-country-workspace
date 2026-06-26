from typing import Any, Protocol

from country_workspace.notifications.bitcaster_client import BitcasterManager


class NotificationBackend(Protocol):
    def trigger_event(self, event_name: str, payload: dict[str, Any]) -> bool: ...


def get_notification_backend() -> NotificationBackend:
    return BitcasterManager()


def send_notification_event(event_name: str, payload: dict[str, Any]) -> bool:
    backend = get_notification_backend()
    return backend.trigger_event(event_name, payload)
