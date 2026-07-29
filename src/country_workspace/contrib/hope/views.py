import logging

from django.core import signing
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, HttpResponseServerError
from django.views import View

from country_workspace.contrib.hope.push.orchestration import (
    DEDUP_CALLBACK_MAX_AGE,
    DEDUP_CALLBACK_SALT,
    dedup_callback_handle,
    PUSH_READY_CALLBACK_MAX_AGE,
    PUSH_READY_CALLBACK_SALT,
    push_ready_callback_handle,
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
                salt=DEDUP_CALLBACK_SALT,
                max_age=DEDUP_CALLBACK_MAX_AGE,
            )
        except signing.SignatureExpired:
            logger.warning("dedup_callback: signed token expired for token prefix=%s", signed_token[:12])
            return HttpResponseForbidden("Token expired.")
        except signing.BadSignature:
            logger.warning("dedup_callback: invalid signed token prefix=%s", signed_token[:12])
            return HttpResponseForbidden("Invalid token.")

        rdp_id = data.get("rdp_id")
        job_id = data.get("job_id")
        if not isinstance(rdp_id, int) or not isinstance(job_id, int):
            logger.warning("dedup_callback: missing or invalid token payload data=%r", data)
            return HttpResponseForbidden("Invalid token payload.")

        try:
            dedup_callback_handle(rdp_id=rdp_id, job_id=job_id)
        except Exception:
            logger.exception("dedup_callback: unhandled error while handling rdp_id=%s job_id=%s", rdp_id, job_id)

        return HttpResponse(status=200)


class PushReadyCallbackView(View):
    """Receive a callback from HOPE when it is ready to accept the RDP."""

    def get(self, request: HttpRequest, signed_token: str) -> HttpResponse:
        try:
            data = signing.loads(
                signed_token,
                salt=PUSH_READY_CALLBACK_SALT,
                max_age=PUSH_READY_CALLBACK_MAX_AGE,
            )
        except signing.SignatureExpired:
            logger.warning("push_ready_callback: token expired prefix=%s", signed_token[:12])
            return HttpResponseForbidden("Token expired.")
        except signing.BadSignature:
            logger.warning("push_ready_callback: invalid token prefix=%s", signed_token[:12])
            return HttpResponseForbidden("Invalid token.")

        rdp_id = data.get("rdp_id")
        rdi_id = data.get("rdi_id")
        prepare_job_id = data.get("prepare_job_id")
        if (
            not isinstance(rdp_id, int)
            or not isinstance(rdi_id, str)
            or not rdi_id
            or not isinstance(prepare_job_id, int)
        ):
            logger.warning(
                "push_ready_callback: invalid token payload data=%r",
                data,
            )
            return HttpResponseForbidden("Invalid token payload.")

        try:
            push_ready_callback_handle(
                rdp_id=rdp_id,
                rdi_id=rdi_id,
                prepare_job_id=prepare_job_id,
            )
        except Exception:
            logger.exception(
                "push_ready_callback: unhandled error for rdp_id=%s rdi_id=%s prepare_job_id=%s",
                rdp_id,
                rdi_id,
                prepare_job_id,
            )
            return HttpResponseServerError()

        return HttpResponse(status=200)
