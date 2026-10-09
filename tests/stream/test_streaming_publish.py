from country_workspace.stream import publish as publish_mod
from country_workspace.stream.publish import OCR_REQUEST_ROUTING_KEY, publish


def test_publish_succeeds_on_first_attempt(mocker):
    manager = mocker.Mock()
    manager.notify.return_value = True
    init = mocker.patch.object(publish_mod, "initialize_engine", return_value=manager)

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is True

    init.assert_called_once_with()
    manager.notify.assert_called_once()


def test_publish_resets_engine_and_retries_after_failure(mocker):
    stale = mocker.Mock()
    stale.notify.return_value = False
    fresh = mocker.Mock()
    fresh.notify.return_value = True
    init = mocker.patch.object(publish_mod, "initialize_engine", side_effect=[stale, fresh])

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is True

    assert init.call_args_list == [mocker.call(), mocker.call(True)]
    stale.notify.assert_called_once()
    fresh.notify.assert_called_once()


def test_publish_returns_false_when_retry_also_fails(mocker):
    stale = mocker.Mock()
    stale.notify.return_value = False
    fresh = mocker.Mock()
    fresh.notify.return_value = False
    mocker.patch.object(publish_mod, "initialize_engine", side_effect=[stale, fresh])

    assert publish(OCR_REQUEST_ROUTING_KEY, {"ok": True}) is False
