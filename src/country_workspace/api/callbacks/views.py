from django.core import signing
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from country_workspace.contrib.hope.constants import (
    PUSH_READY_CALLBACK_MAX_AGE,
    PUSH_READY_CALLBACK_SALT,
)
from country_workspace.contrib.hope.push.orchestration import handle_push_ready_callback

from .serializers import (
    HopeRdpPushReadyCallbackResponseSerializer,
    HopeRdpPushReadyCallbackTokenSerializer,
    ErrorResponseSerializer,
)


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
        response=ErrorResponseSerializer,
        description="The callback token is invalid or expired.",
    ),
    status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiResponse(
        description="The callback could not be processed.",
    ),
}


class HopeRdpPushReadyCallbackView(APIView):
    """Handle signed HOPE push-ready callbacks."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    http_method_names = ["post", "options"]

    @extend_schema(
        request=None,
        responses=PUSH_READY_CALLBACK_RESPONSES,
        tags=["callbacks"],
    )
    def post(self, request: Request, signed_token: str) -> Response:
        """Schedule data push after HOPE confirms reset completion."""
        try:
            payload = signing.loads(
                signed_token,
                salt=PUSH_READY_CALLBACK_SALT,
                max_age=PUSH_READY_CALLBACK_MAX_AGE,
            )
        except signing.BadSignature:
            return Response(
                {"detail": "Invalid callback token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_serializer = HopeRdpPushReadyCallbackTokenSerializer(data=payload)
        if not token_serializer.is_valid():
            return Response(
                {"detail": "Invalid callback token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rdp_id = token_serializer.validated_data["rdp_id"]
        push_attempt_id = token_serializer.validated_data["push_attempt_id"]
        queued = handle_push_ready_callback(
            rdp_id=rdp_id,
            push_attempt_id=push_attempt_id,
        )

        code = "queued" if queued else "ignored"
        response_serializer = HopeRdpPushReadyCallbackResponseSerializer(
            {
                "rdp_id": rdp_id,
                "push_attempt_id": push_attempt_id,
                "code": code,
                "detail": ("Data-push job scheduled." if queued else "Callback already handled or no longer current."),
            }
        )
        response = Response(
            response_serializer.data,
            status=status.HTTP_202_ACCEPTED if queued else status.HTTP_200_OK,
        )
        response["Cache-Control"] = "no-store"
        return response
