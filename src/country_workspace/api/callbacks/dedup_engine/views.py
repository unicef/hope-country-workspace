import sentry_sdk

from django.core import signing
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp import DEDUP_CALLBACK_MAX_AGE, DEDUP_CALLBACK_SALT, sync_deduplication_result

from .responses import (
    DEDUP_CALLBACK_RESPONSES,
    dedup_callback_error_response,
    dedup_callback_response,
    dedup_callback_unavailable_response,
    invalid_callback_token_response,
)
from .serializers import DedupEngineRdpCallbackPayloadSerializer


class DedupEngineRdpStateChangedCallbackView(APIView):
    """Synchronize an RDP after a DedupEngine state change."""

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
        """Synchronize the result identified by the signed URL token."""
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
            synchronized = sync_deduplication_result(
                rdp_id=serializer.validated_data["rdp_id"],
                deduplication_set_id=serializer.validated_data["deduplication_set_id"],
            )
        except RemoteUnavailableError as exc:
            sentry_sdk.capture_exception(exc)
            return dedup_callback_unavailable_response()
        except RemoteError as exc:
            sentry_sdk.capture_exception(exc)
            return dedup_callback_error_response()

        return dedup_callback_response(synchronized=synchronized)
