from uuid import UUID

from drf_spectacular.utils import OpenApiResponse
from rest_framework import status
from rest_framework.response import Response

from .serializers import (
    HopeRdpPushReadyCallbackErrorSerializer,
    HopeRdpPushReadyCallbackResponseSerializer,
)
from .types import PushReadyCallbackCode


PUSH_READY_CALLBACK_RESPONSES = {
    status.HTTP_200_OK: OpenApiResponse(
        response=HopeRdpPushReadyCallbackResponseSerializer,
        description="The callback was already handled or is no longer current.",
    ),
    status.HTTP_202_ACCEPTED: OpenApiResponse(
        response=HopeRdpPushReadyCallbackResponseSerializer,
        description="The data-push job was scheduled.",
    ),
    status.HTTP_400_BAD_REQUEST: OpenApiResponse(
        response=HopeRdpPushReadyCallbackErrorSerializer,
        description="The callback token is invalid or expired.",
    ),
    status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiResponse(
        description="The callback could not be processed.",
    ),
}


def invalid_callback_token_response() -> Response:
    """Return an invalid callback token response."""
    return Response(
        {"detail": "Invalid callback token."},
        status=status.HTTP_400_BAD_REQUEST,
    )


def push_ready_callback_response(*, rdp_id: int, push_attempt_id: UUID, queued: bool) -> Response:
    """Return a HOPE push-ready callback response."""
    serializer = HopeRdpPushReadyCallbackResponseSerializer(
        {
            "rdp_id": rdp_id,
            "push_attempt_id": push_attempt_id,
            "code": PushReadyCallbackCode.QUEUED if queued else PushReadyCallbackCode.IGNORED,
            "detail": "Data-push job scheduled." if queued else "Callback already handled or no longer current.",
        }
    )
    response = Response(
        serializer.data,
        status=status.HTTP_202_ACCEPTED if queued else status.HTTP_200_OK,
    )
    response["Cache-Control"] = "no-store"
    return response
