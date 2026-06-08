import pytest
import responses

from country_workspace.contrib.ona.client import OnaClient
from country_workspace.contrib.ona.exceptions import (
    OnaApiError,
    OnaAuthenticationError,
    OnaRateLimitError,
)


def test_get_submissions_page_uses_token_auth():
    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json=[
                {
                    "_id": 1,
                    "name": "Ahmad",
                }
            ],
            status=200,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="test-token",
            page_size=500,
        )

        result = client.get_submissions_page(
            form_id=9153,
            start=0,
        )

        request = mocked.calls[0].request
        assert request.headers["Authorization"] == "Token test-token"
        assert request.url == "https://data.inform.unicef.org/api/v1/data/9153?start=0&limit=500"

    assert result == [
        {
            "_id": 1,
            "name": "Ahmad",
        }
    ]


def test_iter_submissions_handles_pagination():
    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json=[
                {
                    "_id": 1,
                },
                {
                    "_id": 2,
                },
            ],
            status=200,
        )
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json=[
                {
                    "_id": 3,
                }
            ],
            status=200,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="test-token",
            page_size=2,
        )

        result = list(client.iter_submissions(form_id=9153))

        assert mocked.calls[0].request.url == "https://data.inform.unicef.org/api/v1/data/9153?start=0&limit=2"
        assert mocked.calls[1].request.url == "https://data.inform.unicef.org/api/v1/data/9153?start=2&limit=2"

    assert result == [
        {
            "_id": 1,
        },
        {
            "_id": 2,
        },
        {
            "_id": 3,
        },
    ]


def test_get_form_metadata():
    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/forms/9153",
            json={
                "formid": 9153,
                "title": "INFORM Registration",
            },
            status=200,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="test-token",
        )

        result = client.get_form_metadata(form_id=9153)

    assert result == {
        "formid": 9153,
        "title": "INFORM Registration",
    }


def test_get_raises_authentication_error_on_401():
    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json={
                "detail": "Invalid token",
            },
            status=401,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="bad-token",
        )

        with pytest.raises(OnaAuthenticationError):
            client.get_submissions_page(form_id=9153, start=0)


def test_get_raises_rate_limit_error_on_429():
    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json={
                "detail": "Too many requests",
            },
            status=429,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="test-token",
        )

        with pytest.raises(OnaRateLimitError):
            client.get_submissions_page(form_id=9153, start=0)


def test_get_raises_api_error_on_500():
    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json={
                "detail": "Server error",
            },
            status=500,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="test-token",
        )

        with pytest.raises(OnaApiError):
            client.get_submissions_page(form_id=9153, start=0)


def test_get_submissions_page_rejects_non_list_response():
    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json={
                "unexpected": "object",
            },
            status=200,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="test-token",
        )

        with pytest.raises(OnaApiError):
            client.get_submissions_page(form_id=9153, start=0)