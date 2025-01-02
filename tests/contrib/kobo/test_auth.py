from unittest.mock import Mock

from requests.models import PreparedRequest

from country_workspace.contrib.kobo.api.auth import Auth, AUTHORIZATION, TOKEN


def test_token_is_used() -> None:
    api_key = "test_api_key"
    auth = Auth(api_key)
    request = Mock(spec=PreparedRequest)
    request.headers = {}
    auth(request)
    assert request.headers[AUTHORIZATION] == f"{TOKEN} {api_key}"
