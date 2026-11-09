import logging
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any

from streaming.backends.rabbitmq import RabbitMQBackend
from streaming.manager import ChangeManager, initialize_engine
from streaming.utils import make_event

if TYPE_CHECKING:
    from streaming.event import Event

logger = logging.getLogger(__name__)

OCR_REQUEST_ROUTING_KEY = "hd.ocr.request"


class PublishOutcome(StrEnum):
    SUCCESS = auto()
    NOT_SENT = auto()
    UNKNOWN = auto()


def _publish_once(manager: ChangeManager, routing_key: str, event: "Event") -> PublishOutcome:
    """Publish once while distinguishing definite RabbitMQ connection failures."""
    backend = manager.backend
    if isinstance(backend, RabbitMQBackend):
        try:
            if not backend.channel or backend.channel.is_closed:
                backend.connect(True)
        except Exception as exc:
            logger.error("stream connection failed routing_key=%s", routing_key, exc_info=exc)
            return PublishOutcome.NOT_SENT

    return PublishOutcome.SUCCESS if manager.notify(routing_key, event) else PublishOutcome.UNKNOWN


def publish(routing_key: str, payload: dict[str, Any]) -> PublishOutcome:
    """Publish a payload, resetting a stale streaming engine once on failure."""
    event = make_event(payload)
    outcome = _publish_once(initialize_engine(), routing_key, event)
    if outcome is PublishOutcome.SUCCESS:
        return outcome

    logger.warning(
        "stream publish failed routing_key=%s outcome=%s; resetting engine and retrying", routing_key, outcome
    )
    retry_outcome = _publish_once(initialize_engine(True), routing_key, event)
    if retry_outcome is PublishOutcome.SUCCESS:
        return retry_outcome

    return PublishOutcome.UNKNOWN if PublishOutcome.UNKNOWN in (outcome, retry_outcome) else PublishOutcome.NOT_SENT
