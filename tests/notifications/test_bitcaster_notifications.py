from unittest.mock import Mock

import pytest
import requests

from country_workspace.notifications.bitcaster_client import BitcasterClient, RetryableBitcasterError
from country_workspace.notifications.notifier import send_notification_event
from country_workspace.notifications.tasks import send_bitcaster_event_task


def _configure_bitcaster_settings(settings) -> None:
    settings.BITCASTER_API_URL = "https://bitcaster.example"
    settings.BITCASTER_API_KEY = "secret-key"
    settings.BITCASTER_ORGANIZATION_SLUG = "org"
    settings.BITCASTER_PROJECT_SLUG = "project"
    settings.BITCASTER_APPLICATION_SLUG = "workspace"


def test_trigger_event_uses_bitcaster_trigger_contract(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    post_mock = mocker.patch("country_workspace.notifications.bitcaster_client.requests.post")
    response = Mock(status_code=201)
    response.raise_for_status = Mock()
    post_mock.return_value = response

    client = BitcasterClient()
    result = client.trigger_event("data_imported", {"program_id": 123})

    assert result is True
    post_mock.assert_called_once_with(
        "https://bitcaster.example/api/o/org/p/project/a/workspace/e/data_imported/trigger/",
        json={"context": {"program_id": 123}},
        headers={
            "Authorization": "secret-key",
            "Content-Type": "application/json",
        },
        timeout=10,
    )


def test_trigger_event_raises_retryable_error_for_network_failures(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    mocker.patch(
        "country_workspace.notifications.bitcaster_client.requests.post",
        side_effect=requests.exceptions.Timeout("timeout"),
    )

    with pytest.raises(RetryableBitcasterError):
        BitcasterClient().trigger_event("rdi_pushed", {"program_id": 12})


def test_trigger_event_raises_retryable_error_for_http_5xx(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    post_mock = mocker.patch("country_workspace.notifications.bitcaster_client.requests.post")
    response = Mock(status_code=503)
    response.raise_for_status = Mock()
    post_mock.return_value = response

    with pytest.raises(RetryableBitcasterError, match="server error"):
        BitcasterClient().trigger_event("data_imported", {"program_id": 42})


def test_trigger_event_reraises_http_error(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    post_mock = mocker.patch("country_workspace.notifications.bitcaster_client.requests.post")
    response = Mock(status_code=400)
    response.raise_for_status.side_effect = requests.exceptions.HTTPError("bad request")
    post_mock.return_value = response

    with pytest.raises(requests.exceptions.HTTPError, match="bad request"):
        BitcasterClient().trigger_event("data_imported", {"program_id": 42})


def test_trigger_event_returns_false_when_client_not_configured(settings) -> None:
    settings.BITCASTER_API_URL = ""
    settings.BITCASTER_API_KEY = ""
    settings.BITCASTER_ORGANIZATION_SLUG = ""
    settings.BITCASTER_PROJECT_SLUG = ""
    settings.BITCASTER_APPLICATION_SLUG = ""

    assert BitcasterClient().trigger_event("data_imported", {"program_id": 12}) is False


def test_send_notification_event_delegates_to_backend(mocker) -> None:
    backend = Mock()
    backend.trigger_event.return_value = True
    get_backend = mocker.patch(
        "country_workspace.notifications.notifier.get_notification_backend",
        return_value=backend,
    )

    result = send_notification_event("rdi_pushed", {"program_id": 7})

    assert result is True
    get_backend.assert_called_once_with()
    backend.trigger_event.assert_called_once_with("rdi_pushed", {"program_id": 7})


def test_send_bitcaster_event_task_retries_on_retryable_client_error(mocker) -> None:
    backend = Mock(is_configured=True)
    retry_mock = mocker.patch.object(send_bitcaster_event_task, "retry", side_effect=RuntimeError("retry"))
    mocker.patch("country_workspace.notifications.tasks.get_notification_backend", return_value=backend)
    mocker.patch(
        "country_workspace.notifications.tasks.send_notification_event",
        side_effect=RetryableBitcasterError("temporary"),
    )

    with pytest.raises(RuntimeError, match="retry"):
        send_bitcaster_event_task.run("data_imported", {"program_id": 12})

    retry_mock.assert_called_once()


def test_send_bitcaster_event_task_does_not_retry_on_http_400(mocker) -> None:
    backend = Mock(is_configured=True)
    retry_mock = mocker.patch.object(send_bitcaster_event_task, "retry")
    mocker.patch("country_workspace.notifications.tasks.get_notification_backend", return_value=backend)
    http_error = requests.exceptions.HTTPError("bad request")
    http_error.response = Mock(status_code=400)
    mocker.patch("country_workspace.notifications.tasks.send_notification_event", side_effect=http_error)

    send_bitcaster_event_task.run("data_imported", {"program_id": 12})
    retry_mock.assert_not_called()


def test_send_bitcaster_event_task_logs_warning_when_backend_returns_false(mocker) -> None:
    backend = Mock(is_configured=True)
    warning = mocker.patch("country_workspace.notifications.tasks.logger.warning")
    mocker.patch("country_workspace.notifications.tasks.get_notification_backend", return_value=backend)
    mocker.patch("country_workspace.notifications.tasks.send_notification_event", return_value=False)

    send_bitcaster_event_task.run("data_imported", {"program_id": 12})

    warning.assert_any_call("Bitcaster client returned false for event '%s'", "data_imported")


def test_send_bitcaster_event_task_skips_when_backend_not_configured(mocker) -> None:
    backend = Mock(is_configured=False)
    send_event = mocker.patch("country_workspace.notifications.tasks.send_notification_event")
    mocker.patch("country_workspace.notifications.tasks.get_notification_backend", return_value=backend)

    send_bitcaster_event_task.run("data_imported", {"program_id": 12})

    send_event.assert_not_called()
