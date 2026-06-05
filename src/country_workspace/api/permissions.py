from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from country_workspace.models import APIToken


class CanCallHopeRdiCallback(BasePermission):
    message = "Token does not grant access to the HOPE RDI callback."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.auth, APIToken) and request.auth.grant_type == APIToken.GrantType.HOPE_RDI_CALLBACK
