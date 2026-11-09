from pytest_mock import MockerFixture
from streaming.backends.rabbitmq import RabbitMQBackend
from streaming.exceptions import StreamingConfigError

from country_workspace.stream import PublishOutcome
from country_workspace.stream.publish import OCR_REQUEST_ROUTING_KEY, publish


def test_publish_succeeds_on_first_attempt(mocker: MockerFixture) -> None:
    manager = mocker.Mock()
    manager.notify.return_value = True
    init = mocker.patch("country_workspace.stream.publish.initialize_engine", return_value=manager)
    make_event = mocker.patch("country_workspace.stream.publish.make_event")

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is PublishOutcome.SUCCESS

    make_event.assert_called_once_with({"ok": True})
    init.assert_called_once_with()
    manager.notify.assert_called_once_with(OCR_REQUEST_ROUTING_KEY, make_event.return_value)


def test_publish_resets_engine_and_retries_after_failure(mocker: MockerFixture) -> None:
    stale = mocker.Mock()
    stale.notify.return_value = False
    fresh = mocker.Mock()
    fresh.notify.return_value = True
    init = mocker.patch("country_workspace.stream.publish.initialize_engine", side_effect=[stale, fresh])
    make_event = mocker.patch("country_workspace.stream.publish.make_event")

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is PublishOutcome.SUCCESS

    make_event.assert_called_once_with({"ok": True})
    assert init.call_args_list == [mocker.call(), mocker.call(True)]
    stale.notify.assert_called_once_with(OCR_REQUEST_ROUTING_KEY, make_event.return_value)
    fresh.notify.assert_called_once_with(OCR_REQUEST_ROUTING_KEY, make_event.return_value)


def test_publish_returns_unknown_when_delivery_may_have_started(mocker: MockerFixture) -> None:
    stale = mocker.Mock()
    stale.notify.return_value = False
    fresh = mocker.Mock()
    fresh.backend = mocker.Mock(spec=RabbitMQBackend)
    fresh.backend.channel = None
    fresh.backend.connect.side_effect = StreamingConfigError("unavailable")
    mocker.patch("country_workspace.stream.publish.initialize_engine", side_effect=[stale, fresh])

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is PublishOutcome.UNKNOWN

    stale.notify.assert_called_once()
    fresh.notify.assert_not_called()


def test_publish_returns_not_sent_when_neither_attempt_reaches_publish(mocker: MockerFixture) -> None:
    stale = mocker.Mock()
    stale.backend = mocker.Mock(spec=RabbitMQBackend)
    stale.backend.channel = None
    stale.backend.connect.side_effect = StreamingConfigError("unavailable")
    fresh = mocker.Mock()
    fresh.backend = mocker.Mock(spec=RabbitMQBackend)
    fresh.backend.channel = None
    fresh.backend.connect.side_effect = StreamingConfigError("unavailable")
    mocker.patch("country_workspace.stream.publish.initialize_engine", side_effect=[stale, fresh])

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is PublishOutcome.NOT_SENT

    stale.notify.assert_not_called()
    fresh.notify.assert_not_called()
