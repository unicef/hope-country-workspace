from django.core import signing
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from country_workspace.rdp import PUSH_READY_CALLBACK_MAX_AGE, PUSH_READY_CALLBACK_SALT, handle_push_ready_callback

from .responses import (
    PUSH_READY_CALLBACK_RESPONSES,
    invalid_callback_token_response,
    push_ready_callback_response,
)
from .serializers import (
    HopeRdpPushReadyCallbackRequestSerializer,
    HopeRdpPushReadyCallbackPayloadSerializer,
)


class HopeRdpPushReadyCallbackView(APIView):
    """Handle signed HOPE push-ready callbacks."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    http_method_names = ["post", "options"]

    @extend_schema(
        request=HopeRdpPushReadyCallbackRequestSerializer,
        responses=PUSH_READY_CALLBACK_RESPONSES,
        tags=["callbacks"],
    )
    def post(self, request: Request) -> Response:
        """Schedule data push after HOPE confirms reset completion."""
        request_serializer = HopeRdpPushReadyCallbackRequestSerializer(data=request.data)
        if not request_serializer.is_valid():
            return invalid_callback_token_response()

        try:
            payload = signing.loads(
                request_serializer.validated_data["signed_token"],
                salt=PUSH_READY_CALLBACK_SALT,
                max_age=PUSH_READY_CALLBACK_MAX_AGE,
            )
        except signing.BadSignature:
            return invalid_callback_token_response()

        serializer = HopeRdpPushReadyCallbackPayloadSerializer(data=payload)
        if not serializer.is_valid():
            return invalid_callback_token_response()

        rdp_id = serializer.validated_data["rdp_id"]
        push_attempt_id = serializer.validated_data["push_attempt_id"]
        queued = handle_push_ready_callback(rdp_id=rdp_id, push_attempt_id=push_attempt_id)

        return push_ready_callback_response(
            rdp_id=rdp_id,
            push_attempt_id=push_attempt_id,
            queued=queued,
        )
