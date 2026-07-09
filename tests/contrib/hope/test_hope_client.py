import re
from collections.abc import Generator
from typing import Any

import pytest
import requests
import responses
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.client import HopeClient, sanitize_url
from country_workspace.exceptions import RemoteError

type Signals = tuple[Any, Any]

DUMMY_TOKEN = "dummy_token"
DUMMY_PATH = "dummy_path"
HOPE_API_URL = "https://hope-dummy.org/api/rest"
KEY_VALUE = {"key": "value"}
PEOPLE_PATH = "test/push/people/"
NEXT_URL = f"{HOPE_API_URL}/next/"
ERROR = {
    "bad_request": {"error": "Bad request"},
    "connection": "Connection error",
    "forbidden": {"error": "Forbidden"},
    "invalid_json": "invalid json",
    "not_found": {"error": "Not found"},
    "server": {"error": "Server error"},
}


@pytest.fixture
def client() -> HopeClient:
    return HopeClient(token=DUMMY_TOKEN)


@pytest.fixture
def signals(mocker: MockerFixture) -> Generator[Signals, None, None]:
    from country_workspace.contrib.hope.client import hope_request_end, hope_request_start

    start, end = mocker.Mock(), mocker.Mock()
    hope_request_start.connect(start)
    hope_request_end.connect(end)
    yield start, end
    hope_request_start.disconnect(start)
    hope_request_end.disconnect(end)


def test_sanitize_url() -> None:
    assert sanitize_url("https://hope.org//api///rest/path") == "https://hope.org/api/rest/path"


@override_config(HOPE_API_URL=f"{HOPE_API_URL}//", HOPE_API_TOKEN=DUMMY_TOKEN)
@pytest.mark.parametrize("path", [DUMMY_PATH, f"/{DUMMY_PATH}", f"{DUMMY_PATH}/"])
def test_get_url(path: str) -> None:
    client = HopeClient()

    assert client.get_url(path) == f"{HOPE_API_URL}/{DUMMY_PATH}/"
    assert client.session.headers["Authorization"] == f"Token {DUMMY_TOKEN}"


def test_get_lookup_success(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
) -> None:
    start, end = signals
    mocked_responses.add(responses.GET, client.get_url(DUMMY_PATH), json=KEY_VALUE, status=200)

    assert client.get_lookup(DUMMY_PATH) == KEY_VALUE
    assert start.call_count == end.call_count == 0


@pytest.mark.parametrize(
    ("response_kwargs", "message"),
    [
        ({"json": ERROR["not_found"], "status": 404}, "unexpected status 404. Status: 404."),
        ({"json": ERROR["forbidden"], "status": 403}, "unexpected status 403. Status: 403."),
        ({"body": requests.ConnectionError(ERROR["connection"])}, ERROR["connection"]),
        ({"body": ERROR["invalid_json"], "status": 200}, "invalid JSON response. Status: 200."),
    ],
    ids=["not_found", "forbidden", "request_error", "invalid_json"],
)
def test_get_lookup_errors(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
    response_kwargs: dict[str, Any],
    message: str,
) -> None:
    start, end = signals
    url = client.get_url(DUMMY_PATH)
    mocked_responses.add(responses.GET, url, **response_kwargs)

    with pytest.raises(RemoteError, match=re.escape(f"HopeClient: GET {url} failed: {message}")):
        client.get_lookup(DUMMY_PATH)

    assert start.call_count == end.call_count == 0


@pytest.mark.parametrize(
    ("payloads", "expected", "pages"),
    [
        ([{"results": [{"id": 1}], "next": None}], [{"id": 1}], 1),
        (
            [
                {"results": [{"id": 1}], "next": NEXT_URL},
                {"results": [{"id": 2}], "next": None},
            ],
            [{"id": 1}, {"id": 2}],
            2,
        ),
        ([{"results": [], "next": NEXT_URL}], [], 1),
    ],
    ids=["single_page", "multi_page", "empty_results_break"],
)
def test_get_success(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
    payloads: list[dict[str, Any]],
    expected: list[dict[str, int]],
    pages: int,
) -> None:
    start, end = signals
    for url, payload in zip([client.get_url(DUMMY_PATH), NEXT_URL], payloads, strict=False):
        mocked_responses.add(responses.GET, url, json=payload, status=200)

    assert list(client.get(DUMMY_PATH, params={"p": "v"})) == expected
    assert start.call_count == end.call_count == 1
    assert end.call_args.kwargs["pages"] == pages

    urls = [call.request.url for call in mocked_responses.calls]
    assert len(urls) == pages
    assert "p=v" in urls[0]
    assert all("p=" not in url for url in urls[1:])


@pytest.mark.parametrize(
    ("response_kwargs", "message"),
    [
        ({"json": ERROR["not_found"], "status": 404}, "unexpected status 404. Status: 404."),
        ({"body": requests.RequestException(ERROR["connection"])}, ERROR["connection"]),
        ({"body": ERROR["invalid_json"], "status": 200}, "invalid JSON response. Status: 200."),
        ({"json": {}, "status": 200}, "malformed JSON response. Status: 200."),
        ({"json": ["not a dict"], "status": 200}, "malformed JSON response. Status: 200."),
    ],
    ids=["http_404", "request_error", "invalid_json", "missing_results", "wrong_type"],
)
def test_get_errors(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
    response_kwargs: dict[str, Any],
    message: str,
) -> None:
    start, end = signals
    url = client.get_url(DUMMY_PATH)
    mocked_responses.add(responses.GET, url, **response_kwargs)

    with pytest.raises(RemoteError, match=re.escape(f"HopeClient: GET {url} failed: {message}")):
        list(client.get(DUMMY_PATH, params={"p": "v"}))

    assert start.call_count == 1
    assert end.call_count == 0


def test_post_success(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
) -> None:
    start, end = signals
    mocked_responses.add(responses.POST, client.get_url(DUMMY_PATH), json={"id": 1}, status=201)

    assert client.post(DUMMY_PATH, data=KEY_VALUE) == {"id": 1}
    assert start.call_count == end.call_count == 1
    assert end.call_args.kwargs["data"] == KEY_VALUE


@pytest.mark.parametrize(
    ("response_kwargs", "pattern"),
    [
        ({"json": ERROR["bad_request"], "status": 400}, r"Status: 400\."),
        ({"json": ERROR["server"], "status": 500}, r"Status: 500\."),
        ({"body": ERROR["invalid_json"], "status": 200}, r"invalid JSON response\. Status: 200\."),
        ({"body": requests.ConnectionError(ERROR["connection"])}, re.escape(ERROR["connection"])),
    ],
    ids=["http_400", "http_500", "invalid_json", "request_error"],
)
def test_post_errors(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
    response_kwargs: dict[str, Any],
    pattern: str,
) -> None:
    start, end = signals
    url = client.get_url(DUMMY_PATH)
    mocked_responses.add(responses.POST, url, **response_kwargs)

    with pytest.raises(RemoteError, match=rf"HopeClient: POST {re.escape(url)} failed: .*{pattern}"):
        client.post(DUMMY_PATH, data=KEY_VALUE)

    assert start.call_count == end.call_count == 1


def test_post_people_400_returns_errors(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
) -> None:
    start, end = signals
    errors = [{"name": ["Required"]}]
    mocked_responses.add(responses.POST, client.get_url(PEOPLE_PATH), json=errors, status=400)

    assert client.post(PEOPLE_PATH, data={"people": [{"name": "John"}]}) == {"errors": True, "people": errors}
    assert start.call_count == end.call_count == 1


@pytest.mark.parametrize(
    ("path", "status", "body", "pattern"),
    [
        (PEOPLE_PATH, 500, ERROR["server"], r"Status: 500\."),
        (PEOPLE_PATH, 400, ERROR["invalid_json"], r"invalid JSON response\. Status: 400\."),
        (f"{PEOPLE_PATH}wrong", 400, ERROR["bad_request"], r"Status: 400\."),
    ],
    ids=["wrong_status", "invalid_json", "wrong_path"],
)
def test_post_people_errors(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
    path: str,
    status: int,
    body: dict[str, str] | str,
    pattern: str,
) -> None:
    start, end = signals
    url = client.get_url(path)
    kwargs = {"json": body} if isinstance(body, dict) else {"body": body}
    mocked_responses.add(responses.POST, url, status=status, **kwargs)

    with pytest.raises(RemoteError, match=rf"HopeClient: POST {re.escape(url)} failed: .*{pattern}"):
        client.post(path, data={"people": [{"name": "John"}]})

    assert start.call_count == end.call_count == 1


@pytest.mark.parametrize(
    ("response_kwargs", "expected"),
    [
        ({"json": {"deleted": True}, "status": 200}, {"deleted": True}),
        ({"body": "", "status": 204}, {}),
    ],
    ids=["json_body", "empty_body"],
)
def test_delete_success(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
    response_kwargs: dict[str, Any],
    expected: dict[str, bool],
) -> None:
    start, end = signals
    mocked_responses.add(responses.DELETE, client.get_url(DUMMY_PATH), **response_kwargs)

    assert client.delete(DUMMY_PATH) == expected
    assert start.call_count == end.call_count == 1


@pytest.mark.parametrize(
    ("response_kwargs", "pattern"),
    [
        ({"json": ERROR["server"], "status": 500}, r"Status: 500\."),
        ({"body": ERROR["invalid_json"], "status": 200}, r"invalid JSON response\. Status: 200\."),
        ({"body": requests.ConnectionError(ERROR["connection"])}, re.escape(ERROR["connection"])),
    ],
    ids=["http_500", "invalid_json", "request_error"],
)
def test_delete_errors(
    mocked_responses: responses.RequestsMock,
    signals: Signals,
    client: HopeClient,
    response_kwargs: dict[str, Any],
    pattern: str,
) -> None:
    start, end = signals
    url = client.get_url(DUMMY_PATH)
    mocked_responses.add(responses.DELETE, url, **response_kwargs)

    with pytest.raises(RemoteError, match=rf"HopeClient: DELETE {re.escape(url)} failed: .*{pattern}"):
        client.delete(DUMMY_PATH)

    assert start.call_count == end.call_count == 1
