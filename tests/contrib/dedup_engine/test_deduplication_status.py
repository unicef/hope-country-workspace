import pytest
from pytest_mock import MockerFixture
from country_workspace.contrib.dedup_engine.deduplication_status import (
    CLONEABLE_DEDUPLICATION_SET_STATES,
    PROCESSABLE_DEDUPLICATION_SET_STATES,
    PUSHABLE_DEDUPLICATION_SET_STATES,
    REJECTABLE_DEDUPLICATION_SET_STATES,
    DeduplicationSetState,
    DedupClientStatus,
    DedupResponseStatus,
    get_deduplication_status,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError


@pytest.fixture
def dedup_status_client(mocker: MockerFixture):
    make_client = mocker.patch("country_workspace.contrib.dedup_engine.deduplication_status.make_client")
    client = mocker.MagicMock()
    make_client.return_value.__enter__.return_value = client
    return make_client, client


def test_deduplication_set_state_groups() -> None:
    assert PROCESSABLE_DEDUPLICATION_SET_STATES == (DeduplicationSetState.READY,)
    assert PUSHABLE_DEDUPLICATION_SET_STATES == (DeduplicationSetState.DEDUPLICATED,)
    assert REJECTABLE_DEDUPLICATION_SET_STATES == (DeduplicationSetState.DEDUPLICATED,)
    assert CLONEABLE_DEDUPLICATION_SET_STATES == (
        DeduplicationSetState.ENCODING_FAILED,
        DeduplicationSetState.DEDUPLICATION_FAILED,
        DeduplicationSetState.DEDUPLICATED,
        DeduplicationSetState.REJECTED,
    )


def test_get_deduplication_status_without_deduplication_set_id(mocker: MockerFixture) -> None:
    make_client = mocker.patch("country_workspace.contrib.dedup_engine.deduplication_status.make_client")
    assert get_deduplication_status("PROGRAM_ID", None) == DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status=None,
        findings_count=-1,
    )
    make_client.assert_not_called()


def test_get_deduplication_status(dedup_status_client) -> None:
    make_client, client = dedup_status_client
    client.retrieve_deduplication_set.return_value = {
        "state": "Ready",
        "findings_count": 42,
    }

    assert get_deduplication_status("PROGRAM_ID", "SET_ID") == DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status="Ready",
        findings_count=42,
    )

    make_client.assert_called_once_with("PROGRAM_ID", deduplication_set_id="SET_ID")


def test_get_deduplication_status_does_not_swallow_remote_error(dedup_status_client) -> None:
    _, client = dedup_status_client
    client.retrieve_deduplication_set.side_effect = RemoteError("not found")

    with pytest.raises(RemoteError, match="not found"):
        get_deduplication_status("PROGRAM_ID", "SET_ID")


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

    assert get_deduplication_status("PROGRAM_ID", "SET_ID") == DedupClientStatus(
        response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
        deduplication_set_status=None,
        findings_count=-1,
    )

    capture_exception.assert_called_once_with(exc)


@pytest.mark.parametrize(
    "payload",
    [
        {"state": None, "findings_count": 42},
        {"state": "Ready", "findings_count": "42"},
        {"state": "Ready"},
        {"findings_count": 42},
    ],
    ids=["invalid_state", "invalid_findings_count", "missing_findings_count", "missing_state"],
)
def test_get_deduplication_status_rejects_malformed_payload(dedup_status_client, payload: dict) -> None:
    _, client = dedup_status_client
    client.retrieve_deduplication_set.return_value = payload

    with pytest.raises(RemoteError, match="malformed deduplication set status response"):
        get_deduplication_status("PROGRAM_ID", "SET_ID")
