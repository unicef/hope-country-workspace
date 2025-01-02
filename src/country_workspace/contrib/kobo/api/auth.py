from requests.auth import AuthBase
from requests.models import PreparedRequest


TOKEN = "Token"  # noqa: S105
AUTHORIZATION = "Authorization"

class Auth(AuthBase):
    def __init__(self, api_key: str) -> None:
        self._auth_header = f"{TOKEN} {api_key}"

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers[AUTHORIZATION] = self._auth_header
        return request
