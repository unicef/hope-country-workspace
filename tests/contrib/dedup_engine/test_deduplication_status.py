import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.deduplication_status import (
    DedupClientStatus,
    DedupResponseStatus,
    get_deduplication_status,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError


@pytest.fixture
def dedup_status_client(mocker: MockerFixture):
    make_client = mocker.patch("country_workspace.contrib.dedup_engine.deduplication_status.make_client")
    client = make_client.return_value.__enter__.return_value
    return make_client, client


@pytest.mark.parametrize("deduplication_set_id", [None, ""])
def test_get_deduplication_status_without_deduplication_set_id(
    deduplication_set_id: str | None,
    mocker: MockerFixture,
) -> None:
    make_client = mocker.patch("country_workspace.contrib.dedup_engine.deduplication_status.make_client")

    assert get_deduplication_status("GROUP_ID", deduplication_set_id) == DedupClientStatus(
        DedupResponseStatus.OK,
        None,
        -1,
    )
    make_client.assert_not_called()


def test_get_deduplication_status(dedup_status_client) -> None:
    make_client, client = dedup_status_client
    client.retrieve_deduplication_set.return_value = {"state": "Ready", "findings_count": 42}

    assert get_deduplication_status("GROUP_ID", "SET_ID") == DedupClientStatus(
        DedupResponseStatus.OK,
        "Ready",
        42,
    )
    make_client.assert_called_once_with("GROUP_ID", deduplication_set_id="SET_ID")


def test_get_deduplication_status_does_not_swallow_remote_error(dedup_status_client) -> None:
    _, client = dedup_status_client
    client.retrieve_deduplication_set.side_effect = RemoteError("not found")

    with pytest.raises(RemoteError, match="not found"):
        get_deduplication_status("GROUP_ID", "SET_ID")


def test_get_deduplication_status_when_remote_is_unavailable(
    dedup_status_client,
    mocker: MockerFixture,
) -> None:
    _, client = dedup_status_client
    exc = RemoteUnavailableError("boom")
    client.retrieve_deduplication_set.side_effect = exc
    capture_exception = mocker.patch(
        "country_workspace.contrib.dedup_engine.deduplication_status.sentry_sdk.capture_exception"
    )

    assert get_deduplication_status("GROUP_ID", "SET_ID") == DedupClientStatus(
        DedupResponseStatus.STATUS_UNAVAILABLE,
        None,
        -1,
    )
    capture_exception.assert_called_once_with(exc)


@pytest.mark.parametrize(
    "payload",
    [
        {"state": None, "findings_count": 42},
        {"state": "Ready", "findings_count": "42"},
        {"state": "Ready", "findings_count": True},
        {"state": "Ready"},
        {"findings_count": 42},
    ],
)
def test_get_deduplication_status_rejects_malformed_payload(dedup_status_client, payload: dict) -> None:
    _, client = dedup_status_client
    client.retrieve_deduplication_set.return_value = payload

    with pytest.raises(RemoteError, match="malformed deduplication set status response"):
        get_deduplication_status("GROUP_ID", "SET_ID")
