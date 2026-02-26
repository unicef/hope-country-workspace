from collections.abc import Callable
from datetime import datetime, UTC
from unittest.mock import Mock, call
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
    _get_last_updated_date,
)
from country_workspace.exceptions import RemoteError
from testutils.utils import assert_stdout_contains


def test_safe_get_success(hope_client: HopeClient, records: list[dict]) -> None:
    hope_client.get.return_value = iter(records)
    stats = Stats(add=0, upd=0, errors=[])
    results = list(safe_get(hope_client, EndpointConfig(path="dummy_path"), stats))
    assert results == records
    hope_client.get.assert_called_once_with(path="dummy_path")
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


@pytest.mark.parametrize(
    ("last_update_date", "expected"),
    [(datetime(2025, 12, 22, 5, 33, 0, tzinfo=UTC), "2025-12-22"), (None, None)],
    ids=["has_date", "none"],
)
def test_get_last_updated_date(mocker: MockerFixture, mock_model: Mock, last_update_date, expected) -> None:
    ct = Mock()
    mocker.patch("country_workspace.contrib.hope.sync.base.ContentType.objects.get_for_model", return_value=ct)

    qs = mocker.Mock()
    qs.order_by.return_value.first.return_value = Mock(last_update_date=last_update_date) if last_update_date else None
    flt = mocker.patch("country_workspace.contrib.hope.sync.base.SyncLog.objects.filter", return_value=qs)

    assert _get_last_updated_date(mock_model) == expected
    flt.assert_called_once_with(
        content_type=ct,
        name__isnull=True,
        object_id__isnull=True,
        last_update_date__isnull=False,
    )


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


@pytest.mark.parametrize("defaults", [None, {}], ids=["none", "empty_dict"])
def test_sync_entity_prepare_defaults_empty(
    mock_model: Mock, sync_entity_context, records: list[dict], defaults
) -> None:
    config = SyncConfig(
        model=mock_model,
        endpoint=EndpointConfig(path="dummy_path"),
        prepare_defaults=lambda r: defaults,
    )
    assert sync_entity_context([records[0]], config) == Stats(add=0, upd=0, errors=[])
    mock_model.objects.update_or_create.assert_not_called()


@pytest.mark.parametrize(
    ("exception", "expected_log", "raises", "expected_errors"),
    [
        (SkipRecordError("Test skip"), "Skipped record '1'", False, []),
        (DatabaseError("DB error"), "Failed to sync DB record '1'", True, ["Failed to sync DB record '1': DB error"]),
    ],
    ids=["skip_record", "database_error"],
)
def test_sync_entity_errors(
    mock_model: Mock,
    sync_entity_context,
    out: Mock,
    records: list[dict],
    success_config: SyncConfig,
    exception: Exception,
    expected_log: str,
    raises: bool,
    expected_errors: list[str],
) -> None:
    mock_model.objects.update_or_create.side_effect = exception

    if raises:
        with pytest.raises(HopeSyncError) as exc:
            sync_entity_context([records[0]], success_config)
        for e in expected_errors:
            assert e in str(exc.value)
    else:
        assert sync_entity_context([records[0]], success_config) == {"add": 0, "upd": 0, "errors": []}

    assert_stdout_contains(out, expected_log)


@pytest.mark.parametrize(
    ("use_m2m", "use_post"),
    [(True, False), (False, True), (True, True)],
    ids=["m2m_only", "post_only", "both"],
)
def test_sync_entity_hooks(
    mock_model: Mock,
    sync_entity_context,
    records: list[dict],
    mocker,
    use_m2m: bool,
    use_post: bool,
) -> None:
    m2m_hook = mocker.Mock() if use_m2m else None
    post_process = mocker.Mock() if use_post else None

    config = SyncConfig(
        model=mock_model,
        reference_id="reference_id",
        endpoint=EndpointConfig(path="dummy_path"),
        prepare_defaults=lambda r: {"key": r.get("value")},
        **({"m2m_hook": m2m_hook} if m2m_hook else {}),
        **({"post_process": post_process} if post_process else {}),
    )

    instance = Mock()
    mock_model.objects.update_or_create.return_value = (instance, True)

    tracker = Mock()
    if m2m_hook:
        tracker.attach_mock(m2m_hook, "m2m")
    if post_process:
        tracker.attach_mock(post_process, "post")

    assert sync_entity_context([records[0]], config) == {"add": 1, "upd": 0, "errors": []}

    expected_calls = []
    if m2m_hook:
        expected_calls.append(call.m2m(instance, records[0]))
    if post_process:
        expected_calls.append(call.post(instance, True))
    assert tracker.mock_calls == expected_calls
