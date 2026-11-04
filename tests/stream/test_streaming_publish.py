from pytest_mock import MockerFixture

from country_workspace.stream import publish as publish_mod
from country_workspace.stream.publish import OCR_REQUEST_ROUTING_KEY, publish


def test_publish_succeeds_on_first_attempt(mocker: MockerFixture) -> None:
    manager = mocker.Mock()
    manager.notify.return_value = True
    init = mocker.patch.object(publish_mod, "initialize_engine", return_value=manager)
    make_event = mocker.patch.object(publish_mod, "make_event")

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is True

    make_event.assert_called_once_with({"ok": True})
    init.assert_called_once_with()
    manager.notify.assert_called_once_with(OCR_REQUEST_ROUTING_KEY, make_event.return_value)


def test_publish_resets_engine_and_retries_after_failure(mocker: MockerFixture) -> None:
    stale = mocker.Mock()
    stale.notify.return_value = False
    fresh = mocker.Mock()
    fresh.notify.return_value = True
    init = mocker.patch.object(publish_mod, "initialize_engine", side_effect=[stale, fresh])
    make_event = mocker.patch.object(publish_mod, "make_event")

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is True

    make_event.assert_called_once_with({"ok": True})
    assert init.call_args_list == [mocker.call(), mocker.call(True)]
    stale.notify.assert_called_once_with(OCR_REQUEST_ROUTING_KEY, make_event.return_value)
    fresh.notify.assert_called_once_with(OCR_REQUEST_ROUTING_KEY, make_event.return_value)


def test_publish_returns_false_when_retry_also_fails(mocker: MockerFixture) -> None:
    stale = mocker.Mock()
    stale.notify.return_value = False
    fresh = mocker.Mock()
    fresh.notify.return_value = False
    mocker.patch.object(publish_mod, "initialize_engine", side_effect=[stale, fresh])

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is False
