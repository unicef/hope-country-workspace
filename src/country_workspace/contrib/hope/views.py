import logging

from django.core import signing
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.views import View

from country_workspace.contrib.hope.push.orchestration import (
    _DEDUP_CALLBACK_MAX_AGE,
    _DEDUP_CALLBACK_SIGN_KEY,
    dedup_callback_handle,
)

logger = logging.getLogger(__name__)


class DeduplicationCallbackView(View):
    """Receive a GET ping from the dedup engine when deduplication state changes.

    The URL contains a Django-signed token that encodes ``rdp_id`` and
    ``job_id``.  The token is verified before any action is taken.  The view
    always returns ``200 OK`` so the dedup engine does not retry on failures
    (retries would be driven by the next state-change notification instead).
    """

    def get(self, request: HttpRequest, signed_token: str) -> HttpResponse:
        try:
            data = signing.loads(
                signed_token,
                key=_DEDUP_CALLBACK_SIGN_KEY,
                max_age=_DEDUP_CALLBACK_MAX_AGE,
            )
        except signing.SignatureExpired:
            logger.warning("dedup_callback: signed token expired for token prefix=%s", signed_token[:12])
            return HttpResponseForbidden("Token expired.")
        except signing.BadSignature:
            logger.warning("dedup_callback: invalid signed token prefix=%s", signed_token[:12])
            return HttpResponseForbidden("Invalid token.")

        rdp_id = data.get("rdp_id")
        if not isinstance(rdp_id, int):
            logger.warning("dedup_callback: missing or invalid rdp_id in token data=%r", data)
            return HttpResponseForbidden("Invalid token payload.")

        try:
            dedup_callback_handle(rdp_id=rdp_id)
        except Exception:
            logger.exception("dedup_callback: unhandled error while handling rdp_id=%s", rdp_id)

        return HttpResponse(status=200)
