import json
from collections.abc import Iterator

import pytest
import responses
from requests import Session
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    RequestException,
    Timeout as RequestsTimeout,
)

from country_workspace.contrib.dedup_engine.biographic.client import Client
from country_workspace.contrib.dedup_engine.biographic.endpoint import APIRoot
from country_workspace.exceptions import RemoteError, RemoteUnavailableError

DATASETS = "https://de/api/biographic/afg/prog/datasets/"
DATASET_ID = "5f1d3a0e-8c0b-4f5e-9d7a-2b6c1e4a9f10"
DATASET = f"{DATASETS}{DATASET_ID}/"


@pytest.fixture
def client() -> Iterator[Client]:
    with Session() as session:
        yield Client("afg", "prog", session, APIRoot("https://de"), dataset_id=DATASET_ID)


@pytest.fixture
def rsps() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock() as mock:
        yield mock


@pytest.mark.parametrize("notification_url", [None, "https://cw/callback/"])
def test_create_dataset_sends_the_assigned_dataset_id(
    client: Client, rsps: responses.RequestsMock, notification_url: str | None
) -> None:
    rsps.post(DATASETS, json={"dataset_id": DATASET_ID, "status": "pending"}, status=201)

    result = client.create_dataset(notification_url)

    assert result["dataset_id"] == DATASET_ID
    body = json.loads(rsps.calls[0].request.body)
    if notification_url:
        assert body == {"dataset_id": DATASET_ID, "notification_url": notification_url, "notify": True}
    else:
        assert body == {"dataset_id": DATASET_ID}


def test_requests_address_the_dataset_by_its_assigned_id(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, json={"dataset_id": DATASET_ID, "status": "pending"})

    client.retrieve_dataset()

    assert rsps.calls[0].request.url == DATASET


def test_retrieve_dataset(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, json={"dataset_id": DATASET_ID, "status": "deduplicated"})

    assert client.retrieve_dataset()["status"] == "deduplicated"


def test_retrieve_dataset_or_none_missing(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, status=404)

    assert client.retrieve_dataset_or_none() is None


def test_retrieve_dataset_or_none_found(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, json={"dataset_id": DATASET_ID, "status": "pending"})

    assert client.retrieve_dataset_or_none() == {"dataset_id": DATASET_ID, "status": "pending"}


def test_retrieve_dataset_or_none_other_error(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, status=400)

    with pytest.raises(RemoteError):
        client.retrieve_dataset_or_none()


def test_create_records(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.post(f"{DATASET}records/", json={"received": 1, "records_count": 1})

    result = client.create_records([{"reference_pk": "1", "payload": {"full_name": "A B"}}])

    assert result == {"received": 1, "records_count": 1}
    assert b'"reference_pk": "1"' in rsps.calls[0].request.body


@pytest.mark.parametrize("method", ["approve", "reject", "cancel"])
def test_state_actions(client: Client, rsps: responses.RequestsMock, method: str) -> None:
    rsps.post(f"{DATASET}{method}/", json={"dataset_id": DATASET_ID, "status": "approved"})

    assert getattr(client, method)()["dataset_id"] == DATASET_ID
    assert rsps.calls[0].request.body is None


@pytest.mark.parametrize(
    ("overrides", "body"),
    [(None, None), ({"duplicate_score": 0.9}, b'{"duplicate_score": 0.9}')],
)
def test_process(client: Client, rsps: responses.RequestsMock, overrides: dict | None, body: bytes | None) -> None:
    rsps.post(f"{DATASET}process/", json={"dataset_id": DATASET_ID, "status": "indexing"})

    client.process(overrides)

    assert rsps.calls[0].request.body == (body or b"{}")


def test_retrieve_findings_paginates(client: Client, rsps: responses.RequestsMock) -> None:
    url = f"{DATASET}findings/"
    rsps.get(url, json={"count": 2, "next": "x", "results": [{"reference_pk": "1"}]})
    rsps.get(url, json={"count": 2, "next": None, "results": [{"reference_pk": "2"}]})

    findings = client.retrieve_findings()

    assert [finding["reference_pk"] for finding in findings] == ["1", "2"]
    assert "page=1" in rsps.calls[0].request.url
    assert "page=2" in rsps.calls[1].request.url


def test_retrieve_findings_without_next_link(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(f"{DATASET}findings/", json={"count": 1, "results": [{"reference_pk": "1"}]})

    assert len(client.retrieve_findings()) == 1


def test_retrieve_findings_count_mismatch(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(f"{DATASET}findings/", json={"count": 3, "next": None, "results": [{"reference_pk": "1"}]})

    with pytest.raises(RemoteError, match="count=3"):
        client.retrieve_findings()


@pytest.mark.parametrize(
    ("status", "error"),
    [(400, RemoteError), (404, RemoteError), (500, RemoteUnavailableError), (503, RemoteUnavailableError)],
)
def test_http_errors(client: Client, rsps: responses.RequestsMock, status: int, error: type) -> None:
    rsps.get(DATASET, status=status, body="nope")

    with pytest.raises(error) as exc:
        client.retrieve_dataset()

    assert type(exc.value) is error
    assert f"Status: {status}" in str(exc.value)


@pytest.mark.parametrize("exc", [RequestsConnectionError("down"), RequestsTimeout("slow"), RequestException("boom")])
def test_connection_errors(client: Client, rsps: responses.RequestsMock, exc: Exception) -> None:
    rsps.get(DATASET, body=exc)

    with pytest.raises(RemoteUnavailableError):
        client.retrieve_dataset()


def test_malformed_json(client: Client, rsps: responses.RequestsMock) -> None:
    rsps.get(DATASET, body="not json")

    with pytest.raises(RemoteError):
        client.retrieve_dataset()
