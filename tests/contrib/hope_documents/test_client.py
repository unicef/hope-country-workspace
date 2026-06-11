from base64 import b64encode

import pytest
import responses
from constance.test import override_config
from requests.exceptions import ConnectionError as RequestsConnectionError

from country_workspace.contrib.hope_documents.client import (
    HopeDocumentsClient,
    OcrParams,
    decode_data_uri,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError

API_URL = "https://hope-documents.test"
API_TOKEN = "test-token"
UPLOAD_URL = f"{API_URL}/api/upload/"


def _make_data_uri(content: bytes = b"fake-png", mimetype: str = "image/png") -> str:
    return f"data:{mimetype};base64,{b64encode(content).decode()}"


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_upload_full_extraction(mocked_responses: responses.RequestsMock) -> None:
    payload = {
        "info": {"filename": "doc.png", "extension": "png", "width": 100, "height": 50},
        "loaders": {
            "PILLoader": {"text": "hello world", "error": "", "time": "0.1s"},
        },
        "params": {},
    }
    mocked_responses.add(responses.POST, UPLOAD_URL, json=payload, status=200)

    client = HopeDocumentsClient()
    result = client.upload(b"fake-png", "doc.png")

    assert result == payload
    assert mocked_responses.calls[0].request.headers["Authorization"] == f"Token {API_TOKEN}"


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_upload_pattern_search_found(mocked_responses: responses.RequestsMock) -> None:
    payload = {
        "info": {"filename": "doc.png"},
        "findings": [
            {
                "angle": 0,
                "attempts": 1,
                "error": "",
                "found": True,
                "match": ["ABC123", 0.0],
                "psm": 11,
                "text": "ID: ABC123",
                "time": "0.5s",
            }
        ],
        "params": {},
    }
    mocked_responses.add(responses.POST, UPLOAD_URL, json=payload, status=200)

    client = HopeDocumentsClient()
    result = client.upload(b"fake-png", "doc.png", pattern="ABC123")

    assert result["findings"][0]["found"] is True
    body = mocked_responses.calls[0].request.body
    assert b"ABC123" in body


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_upload_http_error(mocked_responses: responses.RequestsMock) -> None:
    mocked_responses.add(responses.POST, UPLOAD_URL, json={"detail": "Unauthorized"}, status=401)

    client = HopeDocumentsClient()
    with pytest.raises(RemoteError, match="HTTP 401"):
        client.upload(b"fake-png", "doc.png")


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_upload_connection_error(mocked_responses: responses.RequestsMock) -> None:
    mocked_responses.add(responses.POST, UPLOAD_URL, body=RequestsConnectionError("refused"))

    client = HopeDocumentsClient()
    with pytest.raises(RemoteUnavailableError, match="unreachable"):
        client.upload(b"fake-png", "doc.png")


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_check_document_found(mocked_responses: responses.RequestsMock) -> None:
    payload = {
        "info": {},
        "findings": [
            {
                "found": True,
                "match": ["ID-99887", 0.0],
                "text": "Document Number: ID-99887",
            }
        ],
        "params": {},
    }
    mocked_responses.add(responses.POST, UPLOAD_URL, json=payload, status=200)

    client = HopeDocumentsClient()
    result = client.check_document(_make_data_uri(), "ID-99887")

    assert result["found"] is True
    assert result["match"] == ["ID-99887", 0.0]
    assert "ID-99887" in result["text"]


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_check_document_not_found(mocked_responses: responses.RequestsMock) -> None:
    payload = {
        "info": {},
        "findings": [
            {
                "found": False,
                "match": None,
                "text": "some unrelated text",
            }
        ],
        "params": {},
    }
    mocked_responses.add(responses.POST, UPLOAD_URL, json=payload, status=200)

    client = HopeDocumentsClient()
    result = client.check_document(_make_data_uri(), "MISSING-123")

    assert result["found"] is False


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_check_document_empty_findings(mocked_responses: responses.RequestsMock) -> None:
    mocked_responses.add(responses.POST, UPLOAD_URL, json={"info": {}, "findings": []}, status=200)

    client = HopeDocumentsClient()
    result = client.check_document(_make_data_uri(), "ABC")

    assert result == {"found": False, "match": None, "text": ""}


@override_config(HOPE_DOCUMENTS_API_URL=API_URL, HOPE_DOCUMENTS_API_TOKEN=API_TOKEN)
def test_upload_custom_ocr_params(mocked_responses: responses.RequestsMock) -> None:
    mocked_responses.add(responses.POST, UPLOAD_URL, json={"info": {}, "loaders": {}}, status=200)

    client = HopeDocumentsClient()
    client.upload(b"fake-png", "doc.png", params=OcrParams(threshold=200, number_only=True))

    body = mocked_responses.calls[0].request.body
    assert b"200" in body
    assert b"true" in body


def test_decode_data_uri() -> None:
    raw = b"hello"
    uri = f"data:image/jpeg;base64,{b64encode(raw).decode()}"
    decoded_bytes, mimetype = decode_data_uri(uri)
    assert decoded_bytes == raw
    assert mimetype == "image/jpeg"


def test_decode_data_uri_invalid() -> None:
    with pytest.raises(ValueError, match="Invalid data URI"):
        decode_data_uri("not-a-data-uri")
