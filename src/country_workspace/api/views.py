from typing import Any, TYPE_CHECKING, cast

from hope_api_auth.auth import GrantedPermission, LoggingTokenAuthentication
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView


from country_workspace.contrib.hope.exceptions import (
    HopeRdiCallbackConflictError,
    HopeRdiCallbackError,
    HopeRdiCallbackNotFoundError,
)
from country_workspace.contrib.hope.push import HopeRdiCallbackCode, HopeRdiCallbackPayload, apply_hope_rdi_final_status
from .grants import APIGrant
from .serializers import HopeRdiCallbackSerializer

if TYPE_CHECKING:
    from country_workspace.models import APIToken


def _callback_payload(exc: HopeRdiCallbackError) -> dict[str, Any]:
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
    permission = APIGrant.HOPE_RDI_CALLBACK
    serializer_class = HopeRdiCallbackSerializer

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
            return Response(_callback_payload(exc), status=status.HTTP_400_BAD_REQUEST)

        return Response(payload.as_dict())
