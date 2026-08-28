import pytest
from streaming.event import Event

from country_workspace.stream import callbacks as callbacks_mod
from country_workspace.stream.callbacks import handle_event


def _make_event_body(payload: dict) -> bytes:
    return Event(payload=payload).marshall()


def test_handle_event_dispatches_ocr_result(mocker):
    handle_ocr_result = mocker.patch.object(callbacks_mod, "handle_ocr_result")
    payload = {"correlation_id": "abc", "batch_id": "batch-1", "documents": []}
    method = mocker.Mock(routing_key="ocr.result")

    result = handle_event("results", mocker.Mock(), method, mocker.Mock(), _make_event_body(payload))

    handle_ocr_result.assert_called_once_with(payload)
    assert result is True


def test_handle_event_ignores_unknown_routing_key(mocker):
    handle_ocr_result = mocker.patch.object(callbacks_mod, "handle_ocr_result")
    method = mocker.Mock(routing_key="some.other.key")

    result = handle_event("results", mocker.Mock(), method, mocker.Mock(), _make_event_body({"a": 1}))

    handle_ocr_result.assert_not_called()
    assert result is True


def test_handle_event_swallows_handler_exception_and_still_acks(mocker):
    mocker.patch.object(callbacks_mod, "handle_ocr_result", side_effect=RuntimeError("boom"))
    capture = mocker.patch.object(callbacks_mod.sentry_sdk, "capture_exception")
    method = mocker.Mock(routing_key="ocr.result")

    result = handle_event("results", mocker.Mock(), method, mocker.Mock(), _make_event_body({"correlation_id": "x"}))

    assert result is True
    capture.assert_called_once()


def test_handle_event_logs_unexpected_payload_shape_without_raising(mocker):
    """A malformed payload (e.g. not matching the expected dict shape) must not block the queue."""
    mocker.patch.object(callbacks_mod, "handle_ocr_result", side_effect=KeyError("documents"))
    mocker.patch.object(callbacks_mod.sentry_sdk, "capture_exception")
    method = mocker.Mock(routing_key="ocr.result")

    result = handle_event("results", mocker.Mock(), method, mocker.Mock(), _make_event_body({"unexpected": True}))

    assert result is True


@pytest.mark.django_db
def test_handle_event_real_handler_ignores_unknown_correlation_id():
    """Integration-ish check: routing through the real handler (no mocks) for an unknown run is a safe no-op."""
    method_routing_key = "ocr.result"
    body = _make_event_body(
        {
            "correlation_id": "00000000-0000-0000-0000-000000000000",
            "batch_id": "batch-1",
            "batch_total": 1,
            "documents": [],
        }
    )

    class Method:
        routing_key = method_routing_key

    result = handle_event("results", None, Method(), None, body)

    assert result is True
