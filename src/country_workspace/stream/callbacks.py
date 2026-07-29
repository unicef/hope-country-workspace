import logging

from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from streaming.event import Event

logger = logging.getLogger(__name__)


def handle_event(
    queue_name: str,
    ch: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
) -> bool:
    """Foundation callback: log the received event and acknowledge it.

    Business logic (e.g. anomaly detection results) will be added on top of
    this once the message contract with the external service is agreed.
    """
    message = Event.unmarshal(body)
    logger.info(
        "stream event received queue=%s routing_key=%s id=%s",
        queue_name,
        method.routing_key,
        message.id,
    )
    return True
