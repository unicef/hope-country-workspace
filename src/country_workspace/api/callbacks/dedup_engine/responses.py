from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

from .serializers import DedupEngineRdpCallbackErrorSerializer, DedupEngineRdpCallbackResponseSerializer
from .types import DedupCallbackCode


DEDUP_CALLBACK_RESPONSES = {
    status.HTTP_200_OK: OpenApiResponse(
        response=DedupEngineRdpCallbackResponseSerializer,
        description="The RDP was updated, or the callback required no changes.",
    ),
    status.HTTP_400_BAD_REQUEST: OpenApiResponse(
        response=DedupEngineRdpCallbackErrorSerializer,
        description="The callback token is invalid or expired.",
    ),
    status.HTTP_502_BAD_GATEWAY: OpenApiResponse(
        response=DedupEngineRdpCallbackErrorSerializer,
        description="A valid deduplication result could not be retrieved.",
    ),
    status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiResponse(
        response=DedupEngineRdpCallbackErrorSerializer,
        description="Deduplication result synchronization is temporarily unavailable.",
    ),
    status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiResponse(
        description="The callback could not be processed.",
    ),
}


def _callback_response(data: dict[str, str], *, status_code: int) -> Response:
    """Return a non-cacheable callback response."""
    response = Response(data, status=status_code)
    response["Cache-Control"] = "no-store"
    return response


def invalid_callback_token_response() -> Response:
    """Return an invalid callback token response."""
    return _callback_response({"detail": "Invalid callback token."}, status_code=status.HTTP_400_BAD_REQUEST)


def dedup_callback_response(*, synchronized: bool) -> Response:
    """Return a DedupEngine callback response."""
    serializer = DedupEngineRdpCallbackResponseSerializer(
        {
            "code": DedupCallbackCode.UPDATED if synchronized else DedupCallbackCode.UNCHANGED,
            "detail": "RDP deduplication state updated." if synchronized else "No RDP update required.",
        }
    )
    return _callback_response(serializer.data, status_code=status.HTTP_200_OK)


def dedup_callback_error_response() -> Response:
    """Return a deduplication result retrieval error response."""
    return _callback_response(
        {"detail": "Could not retrieve a valid deduplication result."},
        status_code=status.HTTP_502_BAD_GATEWAY,
    )


def dedup_callback_unavailable_response() -> Response:
    """Return a deduplication synchronization unavailable response."""
    return _callback_response(
        {"detail": "Deduplication result synchronization is temporarily unavailable."},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
