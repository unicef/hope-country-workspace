from typing import Any

from streaming.manager import initialize_engine
from streaming.utils import make_event


def publish(routing_key: str, payload: dict[str, Any]) -> bool:
    """Publish a payload to the streaming exchange under the given routing key."""
    manager = initialize_engine()
    return manager.notify(routing_key, make_event(payload))
