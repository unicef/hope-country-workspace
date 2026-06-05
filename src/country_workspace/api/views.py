from http import HTTPMethod
from typing import Any, cast, TYPE_CHECKING

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from country_workspace.contrib.hope.exceptions import (
    HopeRdiCallbackConflictError,
    HopeRdiCallbackError,
    HopeRdiCallbackNotFoundError,
)
from country_workspace.contrib.hope.push import apply_hope_rdi_final_status

from .authentication import APITokenAuthentication
from .permissions import CanCallHopeRdiCallback
from .serializers import HopeRdiCallbackSerializer

if TYPE_CHECKING:
    from country_workspace.models import APIToken, Rdp


def _error_payload(exc: HopeRdiCallbackError) -> dict[str, Any]:
    return exc.args[0] if exc.args and isinstance(exc.args[0], dict) else {"errors": [str(exc)]}


class HopeRdiViewSet(viewsets.GenericViewSet):
    authentication_classes = (APITokenAuthentication,)
    permission_classes = (CanCallHopeRdiCallback,)
    serializer_class = HopeRdiCallbackSerializer
    lookup_url_kwarg = "hope_rdi_id"

    @action(detail=True, methods=(HTTPMethod.POST,), url_path="callback")
    def callback(self, request: Request, hope_rdi_id: str) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        token = cast("APIToken", request.auth)
        callback_status: Rdp.PushStatus = serializer.validated_data["status"]

        try:
            rdp = apply_hope_rdi_final_status(
                hope_rdi_id=hope_rdi_id,
                status=callback_status,
                token=token,
            )
        except HopeRdiCallbackNotFoundError as exc:
            return Response(_error_payload(exc), status=status.HTTP_404_NOT_FOUND)
        except HopeRdiCallbackConflictError as exc:
            return Response(_error_payload(exc), status=status.HTTP_409_CONFLICT)
        except HopeRdiCallbackError as exc:
            return Response(_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "rdp_id": rdp.pk,
                "rdi_id": rdp.hope_rdi_id,
                "status": rdp.status,
            }
        )
