import re
from collections.abc import Callable

import pytest
import requests
import responses
from constance.test import override_config
from cryptography.fernet import Fernet

from country_workspace.contrib.aurora.client import AuroraClient
from country_workspace.contrib.aurora.crypto import ENCRYPTED_CONTENT_TYPE
from country_workspace.exceptions import RemoteError


def _fernet_envelope(data: dict, key: bytes) -> str:
    import json

    json_bytes = json.dumps(data).encode("utf-8")
    token = Fernet(key).encrypt(json_bytes)
    return json.dumps({"payload": token.decode("utf-8")})


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


# ---------------------------------------------------------------------------
# get() use_encryption tests
# ---------------------------------------------------------------------------


@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_get_use_encryption_false_without_key(mocked_responses: responses.RequestsMock, settings) -> None:
    """Without an encryption key, use_encryption=True still falls back to plain JSON."""
    settings.AURORA_PAYLOAD_ENCRYPTION_KEY = ""
    client = AuroraClient()
    url = client._get_url("registration/1/records/")
    payload = {"results": [{"pk": 1}], "next": None}
    mocked_responses.add(responses.GET, url, json=payload, status=200)

    results = list(client.get("registration/1/records/"))

    assert results == [{"pk": 1}]
    sent_headers = mocked_responses.calls[0].request.headers
    assert "Accept" not in sent_headers or sent_headers["Accept"] != ENCRYPTED_CONTENT_TYPE


@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_get_use_encryption_sends_accept_header_when_key_configured(
    mocked_responses: responses.RequestsMock, settings
) -> None:
    """With a key configured, use_encryption=True sends Accept: application/encrypted+json."""
    key = Fernet.generate_key()
    settings.AURORA_PAYLOAD_ENCRYPTION_KEY = key
    client = AuroraClient()
    url = client._get_url("registration/1/records/")
    encrypted_body = _fernet_envelope({"results": [{"pk": 5}], "next": None}, key)
    mocked_responses.add(
        responses.GET,
        url,
        body=encrypted_body,
        status=200,
        content_type=ENCRYPTED_CONTENT_TYPE,
    )

    results = list(client.get("registration/1/records/"))

    assert results == [{"pk": 5}]
    sent_accept = mocked_responses.calls[0].request.headers.get("Accept", "")
    assert ENCRYPTED_CONTENT_TYPE in sent_accept


@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_get_use_encryption_decrypts_paginated_response(mocked_responses: responses.RequestsMock, settings) -> None:
    """use_encryption=True decrypts the Fernet payload and yields all results across pages."""
    key = Fernet.generate_key()
    settings.AURORA_PAYLOAD_ENCRYPTION_KEY = key
    base_url = "https://hope-dummy.org/api/rest/registration/2/records/"
    page2_url = base_url + "?page=2"
    page1 = {"results": [{"pk": 10}, {"pk": 11}], "next": page2_url}
    page2 = {"results": [{"pk": 12}], "next": None}
    mocked_responses.add(
        responses.GET,
        base_url,
        body=_fernet_envelope(page1, key),
        status=200,
        content_type=ENCRYPTED_CONTENT_TYPE,
    )
    mocked_responses.add(
        responses.GET,
        page2_url,
        body=_fernet_envelope(page2, key),
        status=200,
        content_type=ENCRYPTED_CONTENT_TYPE,
    )
    client = AuroraClient()

    results = list(client.get("registration/2/records/"))

    assert results == [{"pk": 10}, {"pk": 11}, {"pk": 12}]


@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_get_use_encryption_raises_remote_error_on_wrong_key(
    mocked_responses: responses.RequestsMock, settings
) -> None:
    """use_encryption=True raises RemoteError if the decryption key is wrong."""
    encrypt_key = Fernet.generate_key()
    wrong_key = Fernet.generate_key()
    settings.AURORA_PAYLOAD_ENCRYPTION_KEY = wrong_key
    client = AuroraClient()
    url = client._get_url("registration/3/records/")
    mocked_responses.add(
        responses.GET,
        url,
        body=_fernet_envelope({"results": [], "next": None}, encrypt_key),
        status=200,
        content_type=ENCRYPTED_CONTENT_TYPE,
    )

    with pytest.raises(RemoteError, match="invalid or expired key"):
        list(client.get("registration/3/records/"))


@override_config(AURORA_API_URL="https://hope-dummy.org/api/rest", AURORA_API_TOKEN="dummy_token")
def test_get_plain_unaffected_by_encryption_key(mocked_responses: responses.RequestsMock, settings) -> None:
    """get() without use_encryption always uses plain JSON regardless of encryption key."""
    key = Fernet.generate_key()
    settings.AURORA_PAYLOAD_ENCRYPTION_KEY = key
    client = AuroraClient()
    url = client._get_url("project")
    payload = {"results": [{"pk": 7, "name": "Proj"}], "next": None}
    mocked_responses.add(responses.GET, url, json=payload, status=200)

    results = list(client.get("project"))

    assert results == [{"pk": 7, "name": "Proj"}]
