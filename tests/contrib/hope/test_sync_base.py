from typing import Callable
from unittest.mock import Mock
import pytest
from django.db import DatabaseError
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.sync.base import (
    BaseSync,
    LogLevel,
    SkipRecordError,
    SyncConfig,
    EndpointConfig,
    BaseSyncStep,
    sync_context,
)
from country_workspace.exceptions import RemoteError
from tests.extras.testutils.utils import assert_stdout_contains


def test_safe_get_success(base_sync: BaseSync, records: list[dict]) -> None:
    base_sync.client.get.return_value = iter(records)
    results = list(base_sync.safe_get(endpoint=EndpointConfig(path="dummy_path")))
    assert results == records
    assert base_sync.client.get.call_args == ({"path": "dummy_path"},)
    assert base_sync.total.get("errors") is None


@pytest.mark.parametrize(
    ("exception", "expected_error"),
    [
        (RemoteError("Error 404"), "Error 404"),
        (RemoteError("Network error"), "Network error"),
    ],
    ids=["http_error", "network_error"],
)
def test_safe_get_errors(base_sync: BaseSync, exception: Exception, expected_error: str) -> None:
    base_sync.client.get.side_effect = exception
    results = list(base_sync.safe_get(endpoint=EndpointConfig(path="dummy_path")))
    assert results == []
    assert_stdout_contains(base_sync.stdout, expected_error)
    assert any(expected_error in e for e in base_sync.total["errors"])


@pytest.mark.parametrize(
    ("key", "level", "kwargs", "expected_stdout", "expected_errors"),
    [
        ("SYNC_START", LogLevel.INFO, {"entity": "test_model"}, "Start fetching 'test_model'", None),
        (
            "RECORD_SYNC_FAILURE",
            LogLevel.ERROR,
            {"reference_id_val": "123", "error": "Test error"},
            "Failed to sync DB record '123'",
            ["Failed to sync DB record '123': Test error"],
        ),
    ],
    ids=["info_log", "error_log"],
)
def test_emit_log(
    base_sync: BaseSync,
    key: str,
    level: LogLevel,
    kwargs: dict,
    expected_stdout: str,
    expected_errors: list[str] | None,
) -> None:
    base_sync.emit_log(key, level, **kwargs)
    assert_stdout_contains(base_sync.stdout, expected_stdout)
    assert base_sync.total.get("errors") == expected_errors


@pytest.mark.parametrize(
    ("key", "kwargs", "expected_error_contains"),
    [
        ("INVALID_KEY", {"entity": "test"}, "Log key 'INVALID_KEY' not found in MESSAGES configuration."),
        ("SYNC_START", {"invalid_arg": "test"}, r"missing placeholder ''entity''"),
    ],
)
def test_emit_log_errors(base_sync: BaseSync, key: str, kwargs: dict, expected_error_contains: str) -> None:
    with pytest.raises((KeyError, ValueError), match=expected_error_contains):
        base_sync.emit_log(key, LogLevel.INFO, **kwargs)


@pytest.mark.parametrize(
    ("record", "expected_id", "stdout_contains"),
    [
        ({"id": "123"}, "123", None),
        ({"name": "test"}, None, "Skipping record due to missing 'id'"),
    ],
    ids=["valid_id", "missing_id"],
)
def test_validated_reference_id(
    base_sync: BaseSync, record: dict, expected_id: str | None, stdout_contains: str | None
) -> None:
    assert base_sync.validated_reference_id(record) == expected_id
    if stdout_contains:
        assert_stdout_contains(base_sync.stdout, stdout_contains)
    assert base_sync.total.get("errors") is None


def test_sync_entity_success(
    base_sync: BaseSync,
    mock_model: Mock,
    sync_entity_context: Callable,
    records: list[dict],
    success_config: SyncConfig,
) -> None:
    mock_model.objects.update_or_create.return_value = (Mock(), True)
    sync_entity_context(records=[records[0]], config=success_config)
    assert base_sync.total["test_model"] == {"add": 1, "upd": 0}
    assert base_sync.total.get("errors") is None
    mock_model.objects.update_or_create.assert_called_once_with(reference_id="1", defaults={"key": "test"})


def test_sync_entity_missing_reference_id(
    base_sync: BaseSync,
    mock_model: Mock,
    sync_entity_context: Callable,
    records: list[dict],
    success_config: SyncConfig,
) -> None:
    sync_entity_context(records=[records[2]], config=success_config)
    assert base_sync.total["test_model"] == {"add": 0, "upd": 0}
    assert base_sync.total.get("errors") is None
    assert_stdout_contains(base_sync.stdout, "Skipping record due to missing 'id'")


def test_sync_entity_should_process(
    base_sync: BaseSync,
    mock_model: Mock,
    sync_entity_context: Callable,
    records: list[dict],
    success_config: SyncConfig,
) -> None:
    sync_entity_context(records=[records[1]], config=success_config)
    assert base_sync.total["test_model"] == {"add": 0, "upd": 0}
    assert base_sync.total.get("errors") is None


def test_sync_entity_prepare_defaults_none(
    base_sync: BaseSync, mock_model: Mock, sync_entity_context: Callable, records: list[dict]
) -> None:
    config = SyncConfig(model=mock_model, endpoint=EndpointConfig(path="dummy_path"), prepare_defaults=lambda r: None)
    sync_entity_context(records=[records[0]], config=config)
    assert base_sync.total["test_model"] == {"add": 0, "upd": 0}
    assert base_sync.total.get("errors") is None


@pytest.mark.parametrize(
    ("exception", "expected_log", "expected_errors"),
    [
        (SkipRecordError("Test skip"), "Skipped record '1'", None),
        (DatabaseError("DB error"), "Failed to sync DB record '1'", ["Failed to sync DB record '1': DB error"]),
    ],
    ids=["skip_record", "database_error"],
)
def test_sync_entity_errors(
    base_sync: BaseSync,
    mock_model: Mock,
    sync_entity_context: Callable,
    records: list[dict],
    success_config: SyncConfig,
    exception: Exception,
    expected_log: str,
    expected_errors: list[str] | None,
) -> None:
    mock_model.objects.update_or_create.side_effect = exception
    sync_entity_context(records=[records[0]], config=success_config)
    assert base_sync.total["test_model"] == {"add": 0, "upd": 0}
    assert base_sync.total.get("errors") == expected_errors
    assert_stdout_contains(base_sync.stdout, expected_log)


def test_sync_entity_post_process(
    base_sync: BaseSync, mock_model: Mock, sync_entity_context: Callable, records: list[dict], mocker: MockerFixture
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
    sync_entity_context(records=[records[0]], config=config)
    assert base_sync.total["test_model"] == {"add": 1, "upd": 0}
    assert base_sync.total.get("errors") is None
    mock_model.objects.update_or_create.assert_called_once_with(reference_id="1", defaults={"key": "test"})
    post_process.assert_called_once()


def test_base_sync_step(sync_step: BaseSyncStep, mocker: MockerFixture) -> None:
    sync_method = sync_step._sync_method
    assert sync_step._value_ == 1
    assert sync_step._sync_method == sync_method
    assert sync_step.func == sync_method
    sync_step.func()
    sync_method.assert_called_once()
    assert isinstance(sync_step, BaseSyncStep)


@pytest.mark.parametrize("delta_sync", [True, False], ids=["delta_sync_true", "delta_sync_false"])
@pytest.mark.parametrize(
    ("step", "has_errors", "expected_steps"),
    [
        (None, False, 1),  # All steps
        (Mock(func=Mock()), False, 1),  # Specific step
        (Mock(func=Mock()), True, 1),  # Stop on errors
    ],
    ids=["all_steps", "specific_step", "step_with_errors"],
)
def test_sync_context(
    mocker: MockerFixture,
    delta_sync: bool,
    sync_context_class: type,
    step: BaseSyncStep | None,
    has_errors: bool,
    expected_steps: int,
) -> None:
    def mock_error_step(step):
        def mock_step_func(sync):
            def inner():
                sync.emit_log("RECORD_SYNC_FAILURE", LogLevel.ERROR, reference_id_val="test", error="Test error")

            return inner

        step.func.side_effect = mock_step_func
        mocker.patch.object(sync_context_class, "SyncStep", [step])

    if step:
        step.func.reset_mock()
        if has_errors:
            mock_error_step(step)
    result = sync_context(sync_context_class, delta_sync=delta_sync, step=step, stdout=mocker.Mock())
    expected_total = {"errors": ["Failed to sync DB record 'test': Test error"]} if has_errors and step else {}
    assert result == expected_total

    if step:
        step.func.assert_called_once()
    else:
        sync_context_class.SyncStep[0].func.assert_called_once()
