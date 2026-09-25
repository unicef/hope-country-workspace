import sentry_sdk

from django.core import signing
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from country_workspace.exceptions import RemoteUnavailableError
from country_workspace.rdp import (
    DEDUP_CALLBACK_MAX_AGE,
    DEDUP_CALLBACK_SALT,
    sync_biometric_deduplication_result,
)

from .responses import (
    DEDUP_CALLBACK_RESPONSES,
    dedup_callback_response,
    dedup_callback_unavailable_response,
    invalid_callback_token_response,
)
from .serializers import DedupEngineRdpCallbackPayloadSerializer


class DedupEngineRdpStateChangedCallbackView(APIView):
    """Synchronize an RDP operation after a DedupEngine state change."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    http_method_names = ["get", "options"]

    @extend_schema(
        request=None,
        responses=DEDUP_CALLBACK_RESPONSES,
        tags=["callbacks"],
    )
    def get(self, request: Request, signed_token: str) -> Response:
        """Synchronize the operation identified by the signed URL token."""
        try:
            payload = signing.loads(
                signed_token,
                salt=DEDUP_CALLBACK_SALT,
                max_age=DEDUP_CALLBACK_MAX_AGE,
            )
        except signing.BadSignature:
            return invalid_callback_token_response()

        serializer = DedupEngineRdpCallbackPayloadSerializer(data=payload)
        if not serializer.is_valid():
            return invalid_callback_token_response()

        try:
            synchronized = sync_biometric_deduplication_result(
                operation_id=serializer.validated_data["operation_id"],
            )
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            return dedup_callback_unavailable_response()

        return dedup_callback_response(synchronized=synchronized)
