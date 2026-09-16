from django.core import signing
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp.deduplication.constants import DEDUP_CALLBACK_MAX_AGE, DEDUP_CALLBACK_SALT
from country_workspace.rdp.deduplication.workflow import sync_deduplication_result

from .serializers import DedupEngineRdpCallbackPayloadSerializer, DedupEngineRdpCallbackResponseSerializer


class DedupEngineRdpStateChangedCallbackView(APIView):
    """Synchronize an RDP after a DedupEngine state change."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    http_method_names = ["get", "options"]

    @extend_schema(
        request=None,
        responses={status.HTTP_200_OK: DedupEngineRdpCallbackResponseSerializer},
        tags=["callbacks"],
    )
    def get(self, request: Request, signed_token: str) -> Response:
        try:
            payload = signing.loads(
                signed_token,
                salt=DEDUP_CALLBACK_SALT,
                max_age=DEDUP_CALLBACK_MAX_AGE,
            )
        except signing.BadSignature:
            return Response({"detail": "Invalid callback token."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = DedupEngineRdpCallbackPayloadSerializer(data=payload)
        if not serializer.is_valid():
            return Response({"detail": "Invalid callback token."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            synchronized = sync_deduplication_result(
                rdp_id=serializer.validated_data["rdp_id"],
                deduplication_set_id=serializer.validated_data["deduplication_set_id"],
            )
        except (RemoteError, RemoteUnavailableError):
            return Response(
                {"detail": "Deduplication result could not be synchronized."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response({"synchronized": synchronized}, status=status.HTTP_200_OK)
