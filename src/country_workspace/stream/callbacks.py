import logging

import sentry_sdk
from django.db import InterfaceError, OperationalError
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from streaming.event import Event
from streaming.exceptions import CallbackRetry

from country_workspace.rdp import handle_ocr_result

logger = logging.getLogger(__name__)

OCR_RESULT_ROUTING_KEY = "hcw.ocr.result"


def handle_event(
    queue_name: str,
    ch: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
) -> bool:
    """Dispatch a received event by routing key.

    Non-retryable failures are logged, reported to Sentry, and acknowledged.
    Transient database failures raise CallbackRetry so django-streaming republishes
    the same event for delayed redelivery.
    """
    routing_key = method.routing_key
    message: Event | None = None

    try:
        message = Event.unmarshal(body)
        logger.info(
            "stream event received queue=%s routing_key=%s id=%s",
            queue_name,
            routing_key,
            message.id,
        )
        if routing_key == OCR_RESULT_ROUTING_KEY:
            handle_ocr_result(message.payload)
    except Exception as exc:
        logger.exception(
            "stream event: failed to process queue=%s routing_key=%s id=%s",
            queue_name,
            routing_key,
            message.id if message is not None else None,
        )
        sentry_sdk.capture_exception()

        if isinstance(exc, (InterfaceError, OperationalError)):
            raise CallbackRetry(str(exc)) from exc

    return True
