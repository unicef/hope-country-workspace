import re
from collections.abc import Callable

import pytest
import requests
import responses
from constance.test import override_config

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.exceptions import RemoteError


@pytest.mark.parametrize(
    ("error_case", "status_code", "body", "expected_error"),
    [
        ("status", 404, {"results": []}, lambda url: f"404 Client Error: Not Found for url: {url}"),
        ("status", 403, {"results": []}, lambda url: f"403 Client Error: Forbidden for url: {url}"),
        (
            "request_exception",
            None,
            requests.RequestException("Connection error"),
            lambda url: f"Remote Error fetching {url}:",
        ),
        ("json_decode", 200, "invalid json", lambda url: f"Wrong JSON response fetching {url}"),
    ],
)
@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_client_exceptions(
    mocked_responses: responses.RequestsMock,
    error_case: str,
    status_code: int,
    body: dict | str,
    expected_error: Callable[[str], str],
) -> None:
    client = AuroraClient()
    path = "dummy_path"
    url = client._get_url(path)

    mapping = {
        "request_exception": lambda: {"body": body},
        "json_decode": lambda: {"body": body, "status": status_code},
        "status": lambda: {"json": body, "status": status_code},
    }
    mocked_responses.add(responses.GET, url, **mapping[error_case]())

    expected_message = expected_error(url)
    with pytest.raises(RemoteError, match=re.escape(expected_message)):
        list(client.get(path))
