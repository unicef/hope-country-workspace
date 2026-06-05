from typing import Any, cast

from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

from country_workspace.models import APIToken


class APITokenAuthentication(TokenAuthentication):
    model = APIToken

    def authenticate_credentials(self, key: str) -> tuple[Any, APIToken]:
        user, token = super().authenticate_credentials(key)
        token = cast("APIToken", token)

        if not token.is_valid_at(timezone.now()):
            raise AuthenticationFailed("Token is expired or not active yet.")

        return user, token
