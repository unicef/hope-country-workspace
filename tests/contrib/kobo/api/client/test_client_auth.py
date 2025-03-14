from unittest.mock import Mock

from requests.models import PreparedRequest

from country_workspace.contrib.kobo.api.client.auth import AUTHORIZATION, TOKEN, Auth


def test_auth_call():
    request = Mock(spec=PreparedRequest)
    request.headers = {}
    auth = Auth(token := "test_api_key")
    result = auth(request)
    assert AUTHORIZATION in result.headers
    assert result.headers[AUTHORIZATION] == f"{TOKEN} {token}"
