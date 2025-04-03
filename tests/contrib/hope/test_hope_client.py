# tests/test_hope_client.py
import re
from collections.abc import Callable
from unittest.mock import Mock

import pytest
import requests
import responses
from constance.test import override_config

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.exceptions import RemoteError


@pytest.fixture
def mock_signals():
    from country_workspace.contrib.hope.client import hope_request_end, hope_request_start

    start_mock = Mock()
    end_mock = Mock()
    hope_request_start.connect(start_mock)
    hope_request_end.connect(end_mock)
    yield start_mock, end_mock
    hope_request_start.disconnect(start_mock)
    hope_request_end.disconnect(end_mock)


def test_get_lookup_success(mocked_responses: responses.RequestsMock, mock_signals):
    start_mock, end_mock = mock_signals
    client = HopeClient(token="dummy_token")
    path = "dummy_path"
    url = client.get_url(path)
    expected_result = {"key": "value"}

    mocked_responses.add(
        responses.GET,
        url,
        json=expected_result,
        status=200,
    )

    result = client.get_lookup(path)
    assert result == expected_result
    assert start_mock.call_count == 0
    assert end_mock.call_count == 0


@pytest.mark.parametrize(
    ("status_code", "body", "expected_error"),
    [
        (404, {"error": "Not found"}, "Error 404 fetching https://hope-dummy.org/api/rest/dummy_path/"),
        (403, {"error": "Forbidden"}, "Error 403 fetching https://hope-dummy.org/api/rest/dummy_path/"),
    ],
)
@override_config(HOPE_API_URL="https://hope-dummy.org/api/rest", HOPE_API_TOKEN="dummy_token")
def test_get_lookup_errors(
    mocked_responses: responses.RequestsMock,
    mock_signals,
    status_code: int,
    body: dict,
    expected_error: str,
):
    start_mock, end_mock = mock_signals
    client = HopeClient()
    path = "dummy_path"
    url = client.get_url(path)

    mocked_responses.add(
        responses.GET,
        url,
        json=body,
        status=status_code,
    )

    with pytest.raises(RemoteError, match=re.escape(expected_error)):
        client.get_lookup(path)
    assert start_mock.call_count == 0
    assert end_mock.call_count == 0


@pytest.mark.parametrize(
    ("pages", "expected_results", "next_url"),
    [
        (1, [{"id": 1, "name": "Test"}], None),
        (2, [{"id": 2, "name": "Test2"}, {"id": 3, "name": "Test3"}], "https://hope-dummy.org/api/rest/next/"),
    ],
)
def test_get_success(mocked_responses: responses.RequestsMock, mock_signals, pages, expected_results, next_url):
    start_mock, end_mock = mock_signals
    client = HopeClient(token="dummy_token")
    path = "dummy_path"
    url = client.get_url(path)
    params = {"param": "value"}

    mocked_responses.add(
        responses.GET,
        url,
        json={"results": [expected_results[0]], "next": next_url},
        status=200,
    )
    if next_url:
        mocked_responses.add(
            responses.GET,
            next_url,
            json={"results": [expected_results[1]], "next": None},
            status=200,
        )

    results = list(client.get(path, params=params))
    assert results == expected_results
    assert start_mock.call_count == 1
    assert end_mock.call_count == 1
    assert start_mock.call_args[1]["url"] == url
    assert end_mock.call_args[1]["pages"] == pages


@pytest.mark.parametrize(
    ("error_case", "status_code", "body", "expected_error"),
    [
        ("status", 404, {"error": "Not found"}, lambda url: f"Error 404 fetching {url}"),
        (
            "request_exception",
            None,
            requests.RequestException("Connection error"),
            lambda url: f"Remote Error fetching {url}",
        ),
        ("json_decode", 200, "invalid json", lambda url: f"Wrong JSON response fetching {url}"),
        ("type_error", 200, ["not a dict"], lambda url: f"Malformed JSON fetching {url}"),
    ],
)
def test_get_errors(
    mocked_responses: responses.RequestsMock,
    mock_signals,
    error_case: str,
    status_code: int | None,
    body: dict | str | list,
    expected_error: Callable[[str], str],
):
    start_mock, end_mock = mock_signals
    client = HopeClient(token="dummy_token")
    path = "dummy_path"
    url = client.get_url(path)
    params = {"param": "value"}

    if error_case == "request_exception":
        mocked_responses.add(responses.GET, url, body=body)
    elif error_case == "json_decode":
        mocked_responses.add(responses.GET, url, body=body, status=status_code)
    else:
        mocked_responses.add(responses.GET, url, json=body, status=status_code)

    expected_message = expected_error(url)
    with pytest.raises(RemoteError, match=re.escape(expected_message)):
        list(client.get(path, params=params))

    assert start_mock.call_count == 1
    assert end_mock.call_count == (
        0 if error_case in ["status", "request_exception", "json_decode", "type_error"] else 1
    )


def test_post_success(mocked_responses: responses.RequestsMock, mock_signals):
    start_mock, end_mock = mock_signals
    client = HopeClient(token="dummy_token")
    path = "dummy_path"
    url = client.get_url(path)
    data = {"key": "value"}
    expected_result = {"id": 1, "name": "Created"}

    mocked_responses.add(
        responses.POST,
        url,
        json=expected_result,
        status=201,
    )

    result = client.post(path, data=data)
    assert result == expected_result
    assert start_mock.call_count == 1
    assert end_mock.call_count == 1
    assert start_mock.call_args[1]["url"] == url
    assert end_mock.call_args[1]["data"] == data


@pytest.mark.parametrize(
    ("status_code", "body", "expected_error"),
    [
        (400, {"error": "Bad request"}, "Error posting to https://hope-dummy.org/api/rest/dummy_path/:"),
        (500, {"error": "Server error"}, "Error posting to https://hope-dummy.org/api/rest/dummy_path/:"),
        (200, "invalid json", "Wrong JSON response posting to https://hope-dummy.org/api/rest/dummy_path/"),
    ],
)
@override_config(HOPE_API_URL="https://hope-dummy.org/api/rest", HOPE_API_TOKEN="dummy_token")
def test_post_errors(
    mocked_responses: responses.RequestsMock,
    mock_signals,
    status_code: int,
    body: dict | str,
    expected_error: str,
):
    start_mock, end_mock = mock_signals
    client = HopeClient()
    path = "dummy_path"
    url = client.get_url(path)
    data = {"key": "value"}

    if isinstance(body, dict):
        mocked_responses.add(responses.POST, url, json=body, status=status_code)
    else:
        mocked_responses.add(responses.POST, url, body=body, status=status_code)

    with pytest.raises(RemoteError, match=re.escape(expected_error)):
        client.post(path, data=data)
    assert start_mock.call_count == 1
    assert end_mock.call_count == 0
