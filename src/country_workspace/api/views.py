from typing import Any, TYPE_CHECKING, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from hope_api_auth.auth import GrantedPermission, LoggingTokenAuthentication

from country_workspace.contrib.hope.exceptions import (
    HopeRdiCallbackConflictError,
    HopeRdiCallbackError,
    HopeRdiCallbackNotFoundError,
)
from country_workspace.contrib.hope.push import HopeRdiCallbackCode, HopeRdiCallbackPayload, apply_hope_rdi_final_status
from .grants import APIGrant
from .serializers import (
    HopeRdiCallbackPayloadSerializer,
    HopeRdiCallbackSerializer,
    HopeRdiCallbackValidationErrorSerializer,
)

if TYPE_CHECKING:
    from country_workspace.models import APIToken


def _payload_response(description: str) -> OpenApiResponse:
    """Return documented callback payload response."""
    return OpenApiResponse(response=HopeRdiCallbackPayloadSerializer, description=description)


CALLBACK_RESPONSES: dict[int, OpenApiResponse] = {
    200: _payload_response("RDP finalized or already finalized."),
    400: OpenApiResponse(
        response=HopeRdiCallbackValidationErrorSerializer,
        description="Invalid request payload.",
    ),
    404: _payload_response("No office-scoped RDP was found for the provided HOPE RDI id."),
    409: _payload_response("RDP exists but can not be finalized from its current status."),
    502: _payload_response("Callback processing failed while syncing a downstream service."),
}


def _callback_payload(exc: HopeRdiCallbackError) -> dict[str, Any]:
    """Return a stable callback error payload."""
    payload = exc.args[0] if exc.args else None
    if isinstance(payload, HopeRdiCallbackPayload):
        return payload.as_dict()
    if isinstance(payload, dict):
        return payload
    return HopeRdiCallbackPayload.error(
        code=HopeRdiCallbackCode.CALLBACK_ERROR,
        detail=str(exc),
    ).as_dict()


class HopeRdiCallbackView(APIView):
    """Handle HOPE RDI final status callbacks."""

    authentication_classes = (LoggingTokenAuthentication,)
    permission_classes = (GrantedPermission,)
    parser_classes = (JSONParser,)
    permission = APIGrant.HOPE_RDI_CALLBACK
    serializer_class = HopeRdiCallbackSerializer

    @extend_schema(
        request=HopeRdiCallbackSerializer,
        responses=CALLBACK_RESPONSES,
        tags=["callbacks"],
    )
    def post(self, request: Request, hope_rdi_id: str) -> Response:
        """Apply a final HOPE RDI status to the matching pushed RDP."""
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payload = apply_hope_rdi_final_status(
                hope_rdi_id=hope_rdi_id,
                status=serializer.validated_data["status"],
                token=cast("APIToken", request.auth),
            )
        except HopeRdiCallbackNotFoundError as exc:
            return Response(_callback_payload(exc), status=status.HTTP_404_NOT_FOUND)
        except HopeRdiCallbackConflictError as exc:
            return Response(_callback_payload(exc), status=status.HTTP_409_CONFLICT)
        except HopeRdiCallbackError as exc:
            return Response(_callback_payload(exc), status=status.HTTP_502_BAD_GATEWAY)

        return Response(payload.as_dict())
