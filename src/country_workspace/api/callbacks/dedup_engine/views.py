import logging

from django.core import signing
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from country_workspace.contrib.hope.push.orchestration import (
    DEDUP_CALLBACK_MAX_AGE,
    DEDUP_CALLBACK_SALT,
    dedup_callback_handle,
)

from .serializers import (
    DeduplicationCallbackErrorSerializer,
    DeduplicationCallbackTokenSerializer,
)


logger = logging.getLogger(__name__)


DEDUPLICATION_CALLBACK_RESPONSES = {
    status.HTTP_200_OK: OpenApiResponse(
        description="The DedupEngine state-change callback was accepted.",
    ),
    status.HTTP_400_BAD_REQUEST: OpenApiResponse(
        response=DeduplicationCallbackErrorSerializer,
        description="The callback token is invalid or expired.",
    ),
}


class DeduplicationCallbackView(APIView):
    """Handle signed DedupEngine state-change callbacks."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    renderer_classes = (JSONRenderer,)
    http_method_names = ["get", "options"]

    @extend_schema(
        request=None,
        responses=DEDUPLICATION_CALLBACK_RESPONSES,
        tags=["callbacks"],
    )
    def get(self, request: Request, signed_token: str) -> Response:
        """Process a DedupEngine state-change callback."""
        try:
            payload = signing.loads(
                signed_token,
                salt=DEDUP_CALLBACK_SALT,
                max_age=DEDUP_CALLBACK_MAX_AGE,
            )
        except signing.BadSignature:
            logger.warning("DedupEngine callback token is invalid or expired.")
            return Response(
                {"detail": "Invalid callback token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DeduplicationCallbackTokenSerializer(data=payload)
        if not serializer.is_valid():
            logger.warning("DedupEngine callback token payload is invalid: %r", payload)
            return Response(
                {"detail": "Invalid callback token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rdp_id = serializer.validated_data["rdp_id"]
        job_id = serializer.validated_data["job_id"]

        try:
            dedup_callback_handle(rdp_id=rdp_id, job_id=job_id)
        except Exception:
            logger.exception(
                "Unhandled DedupEngine callback error for rdp_id=%s job_id=%s",
                rdp_id,
                job_id,
            )

        response = Response(status=status.HTTP_200_OK)
        response["Cache-Control"] = "no-store"
        return response
