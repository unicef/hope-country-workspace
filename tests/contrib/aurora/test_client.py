import pytest
import responses
import requests
import re
from typing import Callable

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.exceptions import RemoteError


@pytest.mark.parametrize(
    ("error_case", "status_code", "body", "expected_error"),
    [
        ("status", 404, {"results": []}, lambda url: f"Error 404 fetching {url}"),
        ("status", 403, {"results": []}, lambda url: f"Error 403 fetching {url}"),
        (
            "request_exception",
            None,
            requests.RequestException("Connection error"),
            lambda url: f"Remote Error fetching {url}",
        ),
        ("json_decode", 200, "invalid json", lambda url: f"Wrong JSON response fetching {url}"),
    ],
)
def test_client_exceptions(
    mocked_responses: responses.RequestsMock,
    error_case: str,
    status_code: int,
    body: dict | str,
    expected_error: Callable[[str], str] | str,
) -> None:
    client = AuroraClient(token="dummy")
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
