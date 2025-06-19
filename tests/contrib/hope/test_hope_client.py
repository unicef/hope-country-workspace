import re
from collections.abc import Generator
from typing import Any
from unittest.mock import Mock

import pytest
import requests
import responses
from constance.test import override_config

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.exceptions import RemoteError


DUMMY_TOKEN = "dummy_token"
DUMMY_PATH = "dummy_path"
HOPE_API_URL = "https://hope-dummy.org/api/rest"
KEY_VALUE = {"key": "value"}
PATH = {
    "people": "test/push/people/",
    "next": "https://hope-dummy.org/api/rest/next/",
}
ERROR = {
    "not_found": {"error": "Not found"},
    "forbidden": {"error": "Forbidden"},
    "bad_request": {"error": "Bad request"},
    "server_error": {"error": "Server error"},
    "invalid_json": "invalid json",
    "connection_error": "Connection error",
}


@pytest.fixture
def client() -> HopeClient:
    return HopeClient(token=DUMMY_TOKEN)


@pytest.fixture
def signals() -> Generator[tuple[Mock, Mock], None, None]:
    from country_workspace.contrib.hope.client import hope_request_end, hope_request_start

    start_mock, end_mock = Mock(), Mock()
    hope_request_start.connect(start_mock)
    hope_request_end.connect(end_mock)
    yield start_mock, end_mock
    hope_request_start.disconnect(start_mock)
    hope_request_end.disconnect(end_mock)


def test_get_lookup_success(
    mocked_responses: responses.RequestsMock, signals: tuple[Mock, Mock], client: HopeClient
) -> None:
    start_mock, end_mock = signals
    mocked_responses.add(responses.GET, client.get_url(DUMMY_PATH), json=KEY_VALUE, status=200)

    result = client.get_lookup(DUMMY_PATH)

    assert result == KEY_VALUE
    assert start_mock.call_count == end_mock.call_count == 0


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (404, f"Error 404 fetching {HOPE_API_URL}/{DUMMY_PATH}/"),
        (403, f"Error 403 fetching {HOPE_API_URL}/{DUMMY_PATH}/"),
    ],
    ids=("not_found", "forbidden"),
)
@override_config(HOPE_API_URL=HOPE_API_URL, HOPE_API_TOKEN=DUMMY_TOKEN)
def test_get_lookup_failure(
    mocked_responses: responses.RequestsMock, signals: tuple[Mock, Mock], status_code: int, expected_error: str
) -> None:
    start_mock, end_mock = signals
    client = HopeClient()
    mocked_responses.add(responses.GET, client.get_url(DUMMY_PATH), json=ERROR["not_found"], status=status_code)

    with pytest.raises(RemoteError, match=re.escape(expected_error)):
        client.get_lookup(DUMMY_PATH)

    assert start_mock.call_count == end_mock.call_count == 0


@pytest.mark.parametrize(
    ("pages", "results", "next_url"),
    [
        (1, [{"id": 1}], None),
        (2, [{"id": 2}, {"id": 3}], PATH["next"]),
    ],
    ids=("single_page", "multi_page"),
)
def test_get_success(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
    pages: int,
    results: list[dict],
    next_url: str | None,
) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)

    mocked_responses.add(responses.GET, url, json={"results": [results[0]], "next": next_url}, status=200)
    if next_url:
        mocked_responses.add(responses.GET, next_url, json={"results": [results[1]], "next": None}, status=200)

    assert list(client.get(DUMMY_PATH, params={"p": "v"})) == results
    assert start_mock.call_count == end_mock.call_count == 1
    assert end_mock.call_args[1]["pages"] == pages


@pytest.mark.parametrize(
    ("case", "status", "body", "error_pattern"),
    [
        ("status", 404, ERROR["not_found"], r"Error 404 fetching"),
        ("request_exception", None, requests.RequestException(ERROR["connection_error"]), r"Remote Error fetching"),
        ("json_decode", 200, ERROR["invalid_json"], r"Wrong JSON response fetching"),
        ("type_error", 200, ["not a dict"], r"Malformed JSON fetching"),
    ],
    ids=("http_404", "connection_error", "invalid_json", "wrong_type"),
)
def test_get_failure(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
    case: str,
    status: int | None,
    body: Any,
    error_pattern: str,
) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)

    if case == "request_exception":
        mocked_responses.add(responses.GET, url, body=body)
    elif case == "json_decode":
        mocked_responses.add(responses.GET, url, body=body, status=status)
    else:
        mocked_responses.add(responses.GET, url, json=body, status=status)

    with pytest.raises(RemoteError, match=error_pattern):
        list(client.get(DUMMY_PATH, params={"p": "v"}))

    assert start_mock.call_count == 1
    assert end_mock.call_count == 0


def test_post_success(mocked_responses: responses.RequestsMock, signals: tuple[Mock, Mock], client: HopeClient) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)
    expected = {"id": 1}
    data = KEY_VALUE

    mocked_responses.add(responses.POST, url, json=expected, status=201)

    assert client.post(DUMMY_PATH, data=data) == expected
    assert start_mock.call_count == end_mock.call_count == 1
    assert end_mock.call_args[1]["data"] == data


@pytest.mark.parametrize(
    ("case", "status", "body", "error_pattern"),
    [
        ("http_400", 400, ERROR["bad_request"], r"HTTP error posting to.*?Status.*?400"),
        ("http_500", 500, ERROR["server_error"], r"HTTP error posting to.*?Status.*?500"),
        ("json_decode", 200, ERROR["invalid_json"], r"Wrong JSON response posting to .*?\. Status"),
        (
            "request_exception",
            None,
            requests.ConnectionError(ERROR["connection_error"]),
            r"Request failed for.*?Connection error",
        ),
    ],
    ids=("http_400", "http_500", "json_decode_error", "request_exception"),
)
def test_post_failure(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
    case: str,
    status: int | None,
    body: Any,
    error_pattern: str,
) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)

    if case == "request_exception":
        mocked_responses.add(responses.POST, url, body=body)
    elif case == "json_decode":
        mocked_responses.add(responses.POST, url, body=body, status=status)
    else:
        mocked_responses.add(responses.POST, url, json=body, status=status)

    with pytest.raises(RemoteError, match=error_pattern):
        client.post(DUMMY_PATH, data=KEY_VALUE)

    assert start_mock.call_count == 1
    assert end_mock.call_count == 0


def test_post_people_success(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
) -> None:
    start_mock, end_mock = signals
    path = PATH["people"]
    errors = [{"name": ["Required"]}]
    data = {"people": [{"name": "John"}]}

    mocked_responses.add(responses.POST, client.get_url(path), json=errors, status=400)

    assert client.post(path, data=data) == {"errors": True, "people": errors}
    assert start_mock.call_count == 1
    assert end_mock.call_count == 0


@pytest.mark.parametrize(
    ("path", "status", "body", "error_pattern"),
    [
        (PATH["people"], 500, ERROR["server_error"], r"HTTP error posting to.*?Status: 500"),
        (PATH["people"], 400, ERROR["invalid_json"], r"Wrong JSON response posting to .*?\. Status: 400"),
        (f"{PATH['people']}wrong_ending", 400, ERROR["bad_request"], r"HTTP error posting to.*?Status: 400"),
    ],
    ids=["wrong_status", "json_error", "wrong_ending"],
)
def test_post_people_failure(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
    path: str,
    status: int,
    body: dict | str,
    error_pattern: str,
) -> None:
    start_mock, end_mock = signals
    data = {"people": [{"name": "John"}]}
    mocked_responses.add(
        responses.POST,
        client.get_url(path),
        **({"json": body} if isinstance(body, dict) else {"body": body}),
        status=status,
    )

    with pytest.raises(RemoteError, match=error_pattern):
        client.post(path, data=data)

    assert start_mock.call_count == 1
    assert end_mock.call_count == 0
