from collections.abc import Callable
from unittest.mock import Mock
import pytest
from django.db import DatabaseError
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.exceptions import HopeSyncError, SkipRecordError
from country_workspace.contrib.hope.sync.base import (
    SyncConfig,
    EndpointConfig,
    Stats,
    safe_get,
    log_to,
    validated_reference_id,
)
from country_workspace.exceptions import RemoteError
from testutils.utils import assert_stdout_contains


def test_safe_get_success(hope_client: HopeClient, records: list[dict]) -> None:
    hope_client.get.return_value = iter(records)
    stats = Stats(add=0, upd=0, errors=[])
    results = list(safe_get(hope_client, EndpointConfig(path="dummy_path"), stats))
    assert results == records
    assert hope_client.get.call_args == ({"path": "dummy_path"},)
    assert stats.get("errors") == []


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (RemoteError("Error 404"), "Error 404"),
        (RemoteError("Network error"), "Network error"),
    ],
    ids=["http_error", "network_error"],
)
def test_safe_get_errors(hope_client: HopeClient, exception: Exception, expected_error: str) -> None:
    hope_client.get.side_effect = exception
    stats = Stats(add=0, upd=0, errors=[])
    with log_to(out := Mock()):
        with pytest.raises(HopeSyncError) as exc:
            list(safe_get(hope_client, EndpointConfig(path="dummy_path"), stats))
    assert expected_error in str(exc.value)
    assert_stdout_contains(out, expected_error)
    assert any(expected_error in e for e in stats["errors"])


@pytest.mark.parametrize(
    ("record", "expected_id", "stdout_contains"),
    [
        ({"id": "123"}, "123", None),
        ({"name": "test"}, None, "Skipping record due to missing 'id'"),
    ],
    ids=["valid_id", "missing_id"],
)
def test_validated_reference_id(record: dict, expected_id: str | None, stdout_contains: str | None) -> None:
    if stdout_contains:
        with log_to(out := Mock()):
            assert validated_reference_id(record) == expected_id
        assert_stdout_contains(out, stdout_contains)
    else:
        assert validated_reference_id(record) == expected_id


def test_sync_entity_success(
    mock_model: Mock,
    sync_entity_context: Callable,
    records: list[dict],
    success_config: SyncConfig,
) -> None:
    mock_model.objects.update_or_create.return_value = (Mock(), True)
    stats = sync_entity_context(records=[records[0]], config=success_config)
    assert stats == {"add": 1, "upd": 0, "errors": []}
    mock_model.objects.update_or_create.assert_called_once_with(reference_id="1", defaults={"key": "test"})


def test_sync_entity_missing_reference_id(
    out: Mock,
    mock_model: Mock,
    sync_entity_context: Callable[[list[dict], SyncConfig], Stats],
    records: list[dict],
    success_config: SyncConfig,
) -> None:
    stats = sync_entity_context([records[2]], success_config)
    assert stats == {"add": 0, "upd": 0, "errors": []}
    assert_stdout_contains(out, "Skipping record due to missing 'id'")


def test_sync_entity_should_process(
    mock_model: Mock,
    sync_entity_context: Callable,
    records: list[dict],
    success_config: SyncConfig,
) -> None:
    stats = sync_entity_context(records=[records[1]], config=success_config)
    assert stats == {"add": 0, "upd": 0, "errors": []}


def test_sync_entity_prepare_defaults_none(
    mock_model: Mock, sync_entity_context: Callable[[list[dict], SyncConfig], Stats], records: list[dict]
) -> None:
    config = SyncConfig(model=mock_model, endpoint=EndpointConfig(path="dummy_path"), prepare_defaults=lambda r: None)
    stats = sync_entity_context([records[0]], config)
    assert stats == {"add": 0, "upd": 0, "errors": []}


@pytest.mark.parametrize(
    ("exception", "expected_log", "expected_errors"),
    [
        (SkipRecordError("Test skip"), "Skipped record '1'", []),
        (DatabaseError("DB error"), "Failed to sync DB record '1'", ["Failed to sync DB record '1': DB error"]),
    ],
    ids=["skip_record", "database_error"],
)
def test_sync_entity_errors(
    mock_model: Mock,
    sync_entity_context: Callable[[list[dict], SyncConfig], Stats],
    out: Mock,
    records: list[dict],
    success_config: SyncConfig,
    exception: Exception,
    expected_log: str,
    expected_errors: list[str] | None,
) -> None:
    mock_model.objects.update_or_create.side_effect = exception
    if expected_errors:
        with pytest.raises(HopeSyncError) as exc:
            sync_entity_context([records[0]], success_config)
        for e in expected_errors:
            assert e in str(exc.value)
    else:
        stats = sync_entity_context([records[0]], success_config)
        assert stats == {"add": 0, "upd": 0, "errors": expected_errors}
    assert_stdout_contains(out, expected_log)


def test_sync_entity_post_process(
    mock_model: Mock,
    sync_entity_context: Callable[[list[dict], SyncConfig], Stats],
    records: list[dict],
    mocker: MockerFixture,
) -> None:
    post_process = mocker.Mock()
    config = SyncConfig(
        model=mock_model,
        reference_id="reference_id",
        endpoint=EndpointConfig(path="dummy_path"),
        prepare_defaults=lambda r: {"key": r.get("value")},
        post_process=post_process,
    )
    mock_model.objects.update_or_create.return_value = (Mock(), True)
    stats = sync_entity_context([records[0]], config)
    assert stats == {"add": 1, "upd": 0, "errors": []}
    mock_model.objects.update_or_create.assert_called_once_with(reference_id="1", defaults={"key": "test"})
    post_process.assert_called_once()
