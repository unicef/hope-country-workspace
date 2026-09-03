import logging

import sentry_sdk
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from streaming.event import Event

from country_workspace.contrib.hope.ocr import handle_ocr_result

logger = logging.getLogger(__name__)

OCR_RESULT_ROUTING_KEY = "hcw.ocr.result"


def handle_event(
    queue_name: str,
    ch: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
) -> bool:
    """Dispatch a received event by routing key and acknowledge it.

    Handlers must stay thin (see docs/src/flows/rdp_ocr.md): any handler
    failure is logged and reported to Sentry, but the message is still
    acked - a malformed/unexpected payload must not block the queue.
    """
    message = Event.unmarshal(body)
    routing_key = method.routing_key
    logger.info(
        "stream event received queue=%s routing_key=%s id=%s",
        queue_name,
        routing_key,
        message.id,
    )

    if routing_key == OCR_RESULT_ROUTING_KEY:
        try:
            handle_ocr_result(message.payload)
        except Exception:
            logger.exception("ocr.result: failed to process event id=%s", message.id)
            sentry_sdk.capture_exception()

    return True
