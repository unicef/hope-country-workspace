import re
from collections.abc import Generator
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
    ("response_kwargs", "expected_prefix"),
    [
        (
            {"json": ERROR["not_found"], "status": 404},
            "unexpected status 404. Status: 404.",
        ),
        (
            {"json": ERROR["forbidden"], "status": 403},
            "unexpected status 403. Status: 403.",
        ),
        (
            {"body": requests.ConnectionError(ERROR["connection_error"])},
            ERROR["connection_error"],
        ),
        (
            {"body": ERROR["invalid_json"], "status": 200},
            "invalid JSON response. Status: 200.",
        ),
    ],
    ids=["not_found", "forbidden", "request_exception", "invalid_json"],
)
def test_get_lookup_failure_paths(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
    response_kwargs: dict,
    expected_prefix: str,
) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)

    mocked_responses.add(responses.GET, url, **response_kwargs)

    with pytest.raises(RemoteError, match=re.escape(f"HopeClient: GET {url} failed: {expected_prefix}")):
        client.get_lookup(DUMMY_PATH)

    assert start_mock.call_count == end_mock.call_count == 0


@override_config(HOPE_API_URL=HOPE_API_URL, HOPE_API_TOKEN=DUMMY_TOKEN)
def test_get_lookup_uses_config_fallback(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
) -> None:
    start_mock, end_mock = signals
    client = HopeClient()
    url = client.get_url(DUMMY_PATH)

    mocked_responses.add(responses.GET, url, json=ERROR["not_found"], status=404)

    expected_prefix = f"HopeClient: GET {url} failed: unexpected status 404. Status: 404."
    with pytest.raises(RemoteError, match=re.escape(expected_prefix)):
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

    urls = [c.request.url for c in mocked_responses.calls]
    assert len(urls) == pages
    assert "p=v" in urls[0]
    assert all("p=" not in u for u in urls[1:])


@pytest.mark.parametrize(
    ("response_kwargs", "expected_prefix"),
    [
        (
            {"json": ERROR["not_found"], "status": 404},
            "HopeClient: GET {url} failed: unexpected status 404. Status: 404.",
        ),
        (
            {"body": requests.RequestException(ERROR["connection_error"])},
            f"HopeClient: GET {{url}} failed: {ERROR['connection_error']}",
        ),
        (
            {"body": ERROR["invalid_json"], "status": 200},
            "HopeClient: GET {url} failed: invalid JSON response. Status: 200.",
        ),
        (
            {"json": ["not a dict"], "status": 200},
            "HopeClient: GET {url} failed: malformed JSON response. Status: 200.",
        ),
    ],
    ids=["http_404", "connection_error", "invalid_json", "wrong_type"],
)
def test_get_failure(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
    response_kwargs: dict,
    expected_prefix: str,
) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)

    mocked_responses.add(responses.GET, url, **response_kwargs)

    with pytest.raises(RemoteError, match=re.escape(expected_prefix.format(url=url))):
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
    ("response_kwargs", "pattern"),
    [
        (
            {"json": ERROR["bad_request"], "status": 400},
            r"HopeClient: POST {url} failed: .*Status: 400\.",
        ),
        (
            {"json": ERROR["server_error"], "status": 500},
            r"HopeClient: POST {url} failed: .*Status: 500\.",
        ),
        (
            {"body": ERROR["invalid_json"], "status": 200},
            r"HopeClient: POST {url} failed: invalid JSON response\. Status: 200\.",
        ),
        (
            {"body": requests.ConnectionError(ERROR["connection_error"])},
            rf"HopeClient: POST {{url}} failed: .*{re.escape(ERROR['connection_error'])}",
        ),
    ],
    ids=("http_400", "http_500", "json_decode_error", "request_exception"),
)
def test_post_failure(
    mocked_responses: responses.RequestsMock,
    signals: tuple[Mock, Mock],
    client: HopeClient,
    response_kwargs: dict,
    pattern: str,
) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)

    mocked_responses.add(responses.POST, url, **response_kwargs)

    with pytest.raises(RemoteError, match=pattern.format(url=re.escape(url))):
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
    ("path", "status", "body", "pattern"),
    [
        (PATH["people"], 500, ERROR["server_error"], r"Status: 500\."),
        (PATH["people"], 400, ERROR["invalid_json"], r"invalid JSON response\. Status: 400\."),
        (f"{PATH['people']}wrong_ending", 400, ERROR["bad_request"], r"Status: 400\."),
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
    pattern: str,
) -> None:
    start_mock, end_mock = signals
    data = {"people": [{"name": "John"}]}
    url = client.get_url(path)

    mocked_responses.add(
        responses.POST,
        url,
        **({"json": body} if isinstance(body, dict) else {"body": body}),
        status=status,
    )

    # prefix must match URL; rest is case-specific
    full = rf"HopeClient: POST {re.escape(url)} failed: .*{pattern}"
    with pytest.raises(RemoteError, match=full):
        client.post(path, data=data)

    assert start_mock.call_count == 1
    assert end_mock.call_count == 0


def test_break_with_empty_results(
    mocked_responses: responses.RequestsMock, signals: tuple[Mock, Mock], client: HopeClient
) -> None:
    start_mock, end_mock = signals
    url = client.get_url(DUMMY_PATH)

    mocked_responses.add(
        responses.GET, url, json={"next": "https://hope-dummy.org/api/rest/another/", "results": []}, status=200
    )

    results = list(client.get(DUMMY_PATH, params={"p": "v"}))

    assert results == []
    assert start_mock.call_count == end_mock.call_count == 1
    assert end_mock.call_args[1]["pages"] == 1

    urls = [c.request.url for c in mocked_responses.calls]
    assert len(urls) == 1
    assert "p=v" in urls[0]
