from requests.auth import AuthBase
from requests.models import PreparedRequest


class Auth(AuthBase):
    def __init__(self, api_key: str) -> None:
        self._auth_header = f"Token {api_key}"

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["Authorization"] = self._auth_header
        return request
