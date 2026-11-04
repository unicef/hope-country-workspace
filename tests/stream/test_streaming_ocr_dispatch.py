import pytest
from django.db import IntegrityError, InterfaceError, OperationalError
from pytest_mock import MockerFixture, MockType
from streaming.event import Event
from streaming.exceptions import CallbackRetry

from country_workspace.models import RdpOperation
from country_workspace.stream import callbacks as callbacks_mod
from country_workspace.stream.callbacks import OCR_RESULT_ROUTING_KEY, handle_event
from testutils.factories import OcrRdpOperationFactory

OCR_RESULTS_QUEUE = "ocr_results"


def _make_event_body(payload: dict[str, object]) -> bytes:
    return Event(payload=payload).marshall()


@pytest.fixture(autouse=True)
def close_connections(mocker: MockerFixture) -> MockType:
    return mocker.patch.object(callbacks_mod, "close_old_connections")


@pytest.fixture
def running_ocr_operation() -> RdpOperation:
    return OcrRdpOperationFactory(status=RdpOperation.Status.RUNNING, attempt=1)


def test_handle_event_dispatches_ocr_result(mocker: MockerFixture, close_connections: MockType) -> None:
    handle_ocr_result = mocker.patch.object(callbacks_mod, "handle_ocr_result")
    calls = mocker.Mock()
    calls.attach_mock(close_connections, "close")
    calls.attach_mock(handle_ocr_result, "handle")
    payload = {"correlation_id": "abc", "batch_id": "batch-1", "documents": []}
    method = mocker.Mock(routing_key=OCR_RESULT_ROUTING_KEY)

    result = handle_event(OCR_RESULTS_QUEUE, mocker.Mock(), method, mocker.Mock(), _make_event_body(payload))

    assert result is True
    assert calls.mock_calls == [mocker.call.close(), mocker.call.handle(payload), mocker.call.close()]


def test_handle_event_ignores_unknown_routing_key(mocker: MockerFixture) -> None:
    handle_ocr_result = mocker.patch.object(callbacks_mod, "handle_ocr_result")
    method = mocker.Mock(routing_key="some.other.key")

    result = handle_event(OCR_RESULTS_QUEUE, mocker.Mock(), method, mocker.Mock(), _make_event_body({"a": 1}))

    handle_ocr_result.assert_not_called()
    assert result is True


@pytest.mark.parametrize("error", [RuntimeError("boom"), IntegrityError("constraint")])
def test_handle_event_returns_true_after_handler_error(
    mocker: MockerFixture, close_connections: MockType, error: Exception
) -> None:
    mocker.patch.object(callbacks_mod, "handle_ocr_result", side_effect=error)
    capture = mocker.patch.object(callbacks_mod.sentry_sdk, "capture_exception")
    method = mocker.Mock(routing_key=OCR_RESULT_ROUTING_KEY)

    result = handle_event(
        OCR_RESULTS_QUEUE, mocker.Mock(), method, mocker.Mock(), _make_event_body({"correlation_id": "x"})
    )

    assert result is True
    capture.assert_called_once()
    assert close_connections.call_count == 2


@pytest.mark.parametrize("body", [b"not-json", b'{"id": "x"}'])
def test_handle_event_returns_true_for_malformed_envelope(
    mocker: MockerFixture, close_connections: MockType, body: bytes
) -> None:
    handle_ocr_result = mocker.patch.object(callbacks_mod, "handle_ocr_result")
    capture = mocker.patch.object(callbacks_mod.sentry_sdk, "capture_exception")
    method = mocker.Mock(routing_key=OCR_RESULT_ROUTING_KEY)

    result = handle_event(OCR_RESULTS_QUEUE, mocker.Mock(), method, mocker.Mock(), body)

    assert result is True
    handle_ocr_result.assert_not_called()
    capture.assert_called_once()
    assert close_connections.call_count == 2


@pytest.mark.parametrize("error_type", [InterfaceError, OperationalError])
def test_handle_event_retries_database_errors(
    mocker: MockerFixture, close_connections: MockType, error_type: type[Exception]
) -> None:
    error = error_type("connection lost")
    handler = mocker.patch.object(callbacks_mod, "handle_ocr_result", side_effect=error)
    calls = mocker.Mock()
    calls.attach_mock(close_connections, "close")
    calls.attach_mock(handler, "handle")
    capture = mocker.patch.object(callbacks_mod.sentry_sdk, "capture_exception")
    method = mocker.Mock(routing_key=OCR_RESULT_ROUTING_KEY)

    with pytest.raises(CallbackRetry) as exc:
        handle_event(OCR_RESULTS_QUEUE, mocker.Mock(), method, mocker.Mock(), _make_event_body({}))

    assert exc.value.__cause__ is error
    capture.assert_called_once()
    assert calls.mock_calls == [mocker.call.close(), mocker.call.handle({}), mocker.call.close()]


@pytest.mark.django_db
def test_handle_event_real_handler_ignores_unknown_correlation_id(
    running_ocr_operation: RdpOperation, mocker: MockerFixture
) -> None:
    handler = mocker.spy(callbacks_mod, "handle_ocr_result")
    capture = mocker.patch.object(callbacks_mod.sentry_sdk, "capture_exception")
    payload: dict[str, object] = {
        "correlation_id": "00000000-0000-0000-0000-000000000000",
        "rdp_id": running_ocr_operation.rdp_id,
        "batch_id": "batch-1",
        "batch_index": 1,
        "batch_total": 1,
        "documents": [{"individual_id": 1, "status": "ok", "found": False, "match": None, "error": None}],
    }
    method = mocker.Mock(routing_key=OCR_RESULT_ROUTING_KEY)

    result = handle_event(OCR_RESULTS_QUEUE, mocker.Mock(), method, mocker.Mock(), _make_event_body(payload))

    assert result is True
    handler.assert_called_once_with(payload)
    capture.assert_not_called()
    running_ocr_operation.refresh_from_db()
    assert running_ocr_operation.status == RdpOperation.Status.RUNNING
