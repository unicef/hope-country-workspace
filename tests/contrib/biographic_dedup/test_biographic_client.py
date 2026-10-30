from collections.abc import Iterator

import pytest
import responses
from requests import Session
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout

from country_workspace.contrib.biographic_dedup.client import BiographicClient
from country_workspace.exceptions import RemoteError, RemoteUnavailableError

BASE = "https://de/api/biographic"
DATASETS = f"{BASE}/afg/prog/datasets/"
DATASET = f"{DATASETS}7/"


@pytest.fixture
def client() -> Iterator[BiographicClient]:
    with Session() as session:
        yield BiographicClient(session=session, base_url=BASE, business_area="afg", program_code="prog", dataset_id=7)


@pytest.fixture
def rsps() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as mock:
        yield mock


def test_datasets_url(client: BiographicClient) -> None:
    assert client.datasets_url == DATASETS


def test_dataset_url_requires_dataset_id(client: BiographicClient) -> None:
    client.dataset_id = None

    with pytest.raises(RemoteError, match="dataset_id"):
        client.retrieve_dataset()


@pytest.mark.parametrize("notification_url", [None, "https://cw/callback/"])
def test_create_dataset(client: BiographicClient, rsps: responses.RequestsMock, notification_url: str | None) -> None:
    client.dataset_id = None
    rsps.post(DATASETS, json={"dataset_id": 11, "status": "pending"}, status=201)

    result = client.create_dataset(notification_url)

    assert result["dataset_id"] == 11
    assert client.dataset_id == 11
    body = rsps.calls[0].request.body
    if notification_url:
        assert notification_url.encode() in body
        assert b'"notify": true' in body
    else:
        assert body == b"{}"


def test_retrieve_dataset(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, json={"dataset_id": 7, "status": "deduplicated"})

    assert client.retrieve_dataset()["status"] == "deduplicated"


def test_retrieve_dataset_or_none(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, status=404)

    assert client.retrieve_dataset_or_none() is None


def test_retrieve_dataset_or_none_found(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, json={"dataset_id": 7, "status": "pending"})

    assert client.retrieve_dataset_or_none() == {"dataset_id": 7, "status": "pending"}


def test_retrieve_dataset_or_none_other_error(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, status=400)

    with pytest.raises(RemoteError):
        client.retrieve_dataset_or_none()


def test_upload_records(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.post(f"{DATASET}records/", json={"created": 1, "updated": 0})

    result = client.upload_records([{"reference_pk": "1", "payload": {"full_name": "A B"}}])  # type: ignore[list-item]

    assert result == {"created": 1, "updated": 0}
    assert b'"reference_pk": "1"' in rsps.calls[0].request.body


@pytest.mark.parametrize(
    ("method", "path"),
    [("approve", "approve"), ("reject", "reject"), ("cancel", "cancel")],
)
def test_state_actions(client: BiographicClient, rsps: responses.RequestsMock, method: str, path: str) -> None:
    rsps.post(f"{DATASET}{path}/", json={"dataset_id": 7, "status": "approved"})

    assert getattr(client, method)()["dataset_id"] == 7


def test_process_sends_overrides(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.post(f"{DATASET}process/", json={"dataset_id": 7, "status": "indexing"})

    client.process({"duplicate_score": 0.9})

    assert rsps.calls[0].request.body == b'{"duplicate_score": 0.9}'


def test_retrieve_findings_paginates(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    url = f"{DATASET}findings/"
    rsps.get(url, json={"count": 2, "next": "x", "results": [{"reference_pk": "1"}]})
    rsps.get(url, json={"count": 2, "next": None, "results": [{"reference_pk": "2"}]})

    findings = client.retrieve_findings()

    assert [f["reference_pk"] for f in findings] == ["1", "2"]
    assert "page=2" in rsps.calls[1].request.url


def test_retrieve_findings_count_mismatch(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.get(f"{DATASET}findings/", json={"count": 3, "next": None, "results": [{"reference_pk": "1"}]})

    with pytest.raises(RemoteError, match="count"):
        client.retrieve_findings()


@pytest.mark.parametrize(
    ("status", "error"),
    [(400, RemoteError), (404, RemoteError), (500, RemoteUnavailableError), (503, RemoteUnavailableError)],
)
def test_http_errors(client: BiographicClient, rsps: responses.RequestsMock, status: int, error: type) -> None:
    rsps.get(DATASET, status=status, body="nope")

    with pytest.raises(error) as exc:
        client.retrieve_dataset()

    assert type(exc.value) is error
    assert f"Status: {status}" in str(exc.value)


@pytest.mark.parametrize("exc", [RequestsConnectionError("down"), RequestsTimeout("slow")])
def test_connection_errors(client: BiographicClient, rsps: responses.RequestsMock, exc: Exception) -> None:
    rsps.get(DATASET, body=exc)

    with pytest.raises(RemoteUnavailableError):
        client.retrieve_dataset()


def test_malformed_json(client: BiographicClient, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, body="not json")

    with pytest.raises(RemoteError):
        client.retrieve_dataset()
