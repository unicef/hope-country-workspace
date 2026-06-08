from http import HTTPMethod
from typing import Any, TYPE_CHECKING, cast

from hope_api_auth.auth import GrantedPermission, LoggingTokenAuthentication
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

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


class HopeRdiViewSet(viewsets.GenericViewSet):
    authentication_classes = (LoggingTokenAuthentication,)
    permission_classes = (GrantedPermission,)
    permission = APIGrant.HOPE_RDI_CALLBACK
    serializer_class = HopeRdiCallbackSerializer
    lookup_url_kwarg = "hope_rdi_id"

    @action(detail=True, methods=(HTTPMethod.POST,), url_path="callback")
    def callback(self, request: Request, hope_rdi_id: str) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = cast("APIToken", request.auth)
        callback_status = serializer.validated_data["status"]

        try:
            payload = apply_hope_rdi_final_status(
                hope_rdi_id=hope_rdi_id,
                status=callback_status,
                token=token,
            )
        except HopeRdiCallbackNotFoundError as exc:
            return Response(_callback_payload(exc), status=status.HTTP_404_NOT_FOUND)
        except HopeRdiCallbackConflictError as exc:
            return Response(_callback_payload(exc), status=status.HTTP_409_CONFLICT)
        except HopeRdiCallbackError as exc:
            return Response(_callback_payload(exc), status=status.HTTP_400_BAD_REQUEST)

        return Response(payload.as_dict())
