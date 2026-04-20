from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.deduplication_status import (
    DedupClientStatus,
    DedupResponseStatus,
    get_deduplication_status,
)
from country_workspace.exceptions import RemoteUnavailableError


def test_get_deduplication_status_without_deduplication_set_id() -> None:
    assert get_deduplication_status("PROGRAM_ID", None) == DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status=None,
        findings_count=-1,
    )


def test_get_deduplication_status(mocker: MockerFixture) -> None:
    make_client_mock = mocker.patch("country_workspace.contrib.dedup_engine.deduplication_status.make_client")
    client = mocker.MagicMock()
    make_client_mock.return_value.__enter__.return_value = client
    client.retrieve_deduplication_set.return_value = {
        "state": "Ready",
        "findings_count": 42,
    }

    assert get_deduplication_status("PROGRAM_ID", "SET_ID") == DedupClientStatus(
        response_status=DedupResponseStatus.OK,
        deduplication_set_status="Ready",
        findings_count=42,
    )

    make_client_mock.assert_called_once_with("PROGRAM_ID", deduplication_set_id="SET_ID")


def test_get_deduplication_status_when_remote_is_unavailable(mocker: MockerFixture) -> None:
    make_client_mock = mocker.patch("country_workspace.contrib.dedup_engine.deduplication_status.make_client")
    client = mocker.MagicMock()
    make_client_mock.return_value.__enter__.return_value = client
    client.retrieve_deduplication_set.side_effect = RemoteUnavailableError("boom")
    capture_exception_mock = mocker.patch(
        "country_workspace.contrib.dedup_engine.deduplication_status.sentry_sdk.capture_exception"
    )

    assert get_deduplication_status("PROGRAM_ID", "SET_ID") == DedupClientStatus(
        response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
        deduplication_set_status=None,
        findings_count=-1,
    )

    capture_exception_mock.assert_called_once_with(client.retrieve_deduplication_set.side_effect)
