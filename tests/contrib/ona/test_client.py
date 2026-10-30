import json
from urllib.parse import parse_qs, urlsplit

import pytest
import responses

from country_workspace.contrib.ona.client import OnaClient
from country_workspace.contrib.ona.exceptions import (
    OnaApiError,
    OnaAttachmentTooLargeError,
    OnaAuthenticationError,
    OnaNotFoundError,
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
        assert "start=0" in request.url
        assert "limit=500" in request.url
        params = parse_qs(urlsplit(request.url).query)
        assert json.loads(params["sort"][0]) == {"_id": 1}
        assert "query" not in params

    assert result == [
        {
            "_id": 1,
            "name": "Ahmad",
        }
    ]


@pytest.mark.parametrize("last_id", [None, 0, 100])
def test_iter_submissions_handles_pagination(last_id):
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
        mocked.add(
            responses.GET,
            "https://data.inform.unicef.org/api/v1/data/9153",
            json=[],
            status=200,
        )

        client = OnaClient(
            base_url="https://data.inform.unicef.org",
            token="test-token",
            page_size=2,
        )

        result = list(client.iter_submissions(form_id=9153, last_id=last_id))

        assert "start=0" in mocked.calls[0].request.url
        assert "limit=2" in mocked.calls[0].request.url
        assert "sort=" in mocked.calls[0].request.url
        assert "start=2" in mocked.calls[1].request.url
        assert "limit=2" in mocked.calls[1].request.url
        assert "sort=" in mocked.calls[1].request.url
        assert "start=3" in mocked.calls[2].request.url
        assert "limit=2" in mocked.calls[2].request.url
        assert "sort=" in mocked.calls[2].request.url
        assert len(mocked.calls) == 3
        for call in mocked.calls:
            params = parse_qs(urlsplit(call.request.url).query)
            assert json.loads(params["sort"][0]) == {"_id": 1}
            if last_id is None:
                assert "query" not in params
            else:
                assert json.loads(params["query"][0]) == {"_id": {"$gt": last_id}}

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


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_get_retries_transient_errors(status):
    with responses.RequestsMock() as mocked:
        url = "https://data.inform.unicef.org/api/v1/forms/9153"
        mocked.get(url, status=status)
        mocked.get(url, json={"formid": 9153})
        client = OnaClient(base_url="https://data.inform.unicef.org", token="test-token")

        assert client.get_form_metadata(9153) == {"formid": 9153}
        assert len(mocked.calls) == 2
        assert all(call.request.headers["Authorization"] == "Token test-token" for call in mocked.calls)


@pytest.mark.parametrize(
    ("status", "exception"), [(429, OnaRateLimitError), (503, OnaApiError), (403, OnaAuthenticationError)]
)
def test_get_preserves_errors_after_retry_budget(status, exception):
    with responses.RequestsMock() as mocked:
        mocked.get("https://data.inform.unicef.org/api/v1/forms/9153", status=status)
        client = OnaClient(base_url="https://data.inform.unicef.org", token="test-token")

        with pytest.raises(exception):
            client.get_form_metadata(9153)
        assert len(mocked.calls) == (1 if status == 403 else 4)


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/files/1152251?filename=user/attachments/form/photo.jpg",
        "https://data.inform.unicef.org/api/v1/files/1152251?filename=user/attachments/form/photo.jpg",
    ],
)
def test_download_returns_attachment_content(url):
    with responses.RequestsMock() as mocked:
        mocked.get(
            "https://data.inform.unicef.org/api/v1/files/1152251",
            body=b"\xff\xd8\xffphoto",
            content_type="image/jpeg",
            match=[responses.matchers.query_param_matcher({"filename": "user/attachments/form/photo.jpg"})],
        )
        client = OnaClient(base_url="https://data.inform.unicef.org/", token="test-token")

        assert client.download(url) == b"\xff\xd8\xffphoto"
        assert mocked.calls[0].request.headers["Authorization"] == "Token test-token"


def test_download_refuses_a_url_outside_the_ona_server():
    with responses.RequestsMock():
        client = OnaClient(base_url="https://data.inform.unicef.org", token="test-token")

        with pytest.raises(OnaApiError, match="outside"):
            client.download("https://data.inform.unicef.org.evil.example/api/v1/files/1")


@pytest.mark.parametrize(
    ("status", "exception"),
    [(404, OnaNotFoundError), (410, OnaNotFoundError), (401, OnaAuthenticationError), (500, OnaApiError)],
)
def test_download_raises_on_error_status(status, exception):
    with responses.RequestsMock() as mocked:
        mocked.get("https://data.inform.unicef.org/api/v1/files/1", status=status)
        client = OnaClient(base_url="https://data.inform.unicef.org", token="test-token")

        with pytest.raises(exception):
            client.download("/api/v1/files/1")


@pytest.mark.parametrize(
    ("max_download_bytes", "size"),
    [(None, 1024 * 1024), (1024 * 1024, 1024 * 1024)],
)
def test_download_accepts_attachment_within_limit(max_download_bytes, size):
    with responses.RequestsMock() as mocked:
        mocked.get("https://data.inform.unicef.org/api/v1/files/1", body=b"x" * size)
        client = OnaClient(
            base_url="https://data.inform.unicef.org", token="test-token", max_download_bytes=max_download_bytes
        )

        assert len(client.download("/api/v1/files/1")) == size


@pytest.mark.parametrize("declared", [True, False], ids=["content_length", "streamed"])
def test_download_refuses_attachment_over_limit(declared):
    with responses.RequestsMock() as mocked:
        mocked.get(
            "https://data.inform.unicef.org/api/v1/files/1",
            body=b"x" * (200 * 1024),
            auto_calculate_content_length=declared,
        )
        client = OnaClient(base_url="https://data.inform.unicef.org", token="test-token", max_download_bytes=100 * 1024)

        with pytest.raises(OnaAttachmentTooLargeError, match="exceeds 102400 bytes"):
            client.download("/api/v1/files/1")


def test_retry_backoff_and_retry_after():
    from urllib3.response import HTTPResponse

    client = OnaClient(base_url="https://data.inform.unicef.org", token="test-token")
    retry = client.session.get_adapter(client.base_url).max_retries
    assert retry.allowed_methods == frozenset(("GET",))
    assert retry.respect_retry_after_header is True
    response = HTTPResponse(status=503, headers={"Retry-After": "7"})
    assert retry.get_retry_after(response) == 7
    retry = retry.increment(method="GET", response=response)
    retry = retry.increment(method="GET", response=response)
    assert retry.get_backoff_time() == 2
