from unittest.mock import Mock

import pytest

from country_workspace.notifications.bitcaster_client import BitcasterManager
from country_workspace.notifications.notifier import send_notification_event
from country_workspace.notifications.bitcaster_client import NotifyError
from country_workspace.notifications.tasks import send_bitcaster_event_task


def _configure_bitcaster_settings(settings) -> None:
    settings.BITCASTER_ENABLED = True
    settings.BITCASTER_API_URL = "https://bitcaster.example"
    settings.BITCASTER_API_KEY = "secret-key"
    settings.BITCASTER_ORGANIZATION_SLUG = "org"
    settings.BITCASTER_PROJECT_SLUG = "project"
    settings.BITCASTER_APPLICATION_SLUG = "workspace"


def test_trigger_event_uses_bitcaster_trigger_contract(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    sdk_client = mocker.patch("country_workspace.notifications.bitcaster_client.SDKClient")

    client = BitcasterManager()
    result = client.trigger_event("data_imported", {"program_id": 123})

    assert result is True
    sdk_client.assert_called_once_with(bae="https://secret-key@bitcaster.example/api/o/org/")
    sdk_client.return_value.trigger.assert_called_once_with(
        project="project",
        application="workspace",
        event="data_imported",
        context={"program_id": 123},
    )


def test_trigger_event_propagates_sdk_errors(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    sdk_client = mocker.patch("country_workspace.notifications.bitcaster_client.SDKClient")
    sdk_client.return_value.trigger.side_effect = RuntimeError("boom")

    with pytest.raises(NotifyError, match="boom"):
        BitcasterManager().trigger_event("rdi_push_completed", {"program_id": 12})


def test_trigger_event_returns_false_when_client_not_configured(settings) -> None:
    settings.BITCASTER_API_URL = ""
    settings.BITCASTER_API_KEY = ""
    settings.BITCASTER_ORGANIZATION_SLUG = ""
    settings.BITCASTER_PROJECT_SLUG = ""
    settings.BITCASTER_APPLICATION_SLUG = ""

    assert BitcasterManager().trigger_event("data_imported", {"program_id": 12}) is False


def test_send_notification_event_delegates_to_backend(mocker) -> None:
    backend = Mock()
    backend.trigger_event.return_value = True
    get_backend = mocker.patch(
        "country_workspace.notifications.notifier.get_notification_backend",
        return_value=backend,
    )

    result = send_notification_event("rdi_push_completed", {"program_id": 7})

    assert result is True
    get_backend.assert_called_once_with()
    backend.trigger_event.assert_called_once_with("rdi_push_completed", {"program_id": 7})


def test_send_bitcaster_event_task_logs_error_on_exception(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    backend = Mock(is_configured=True)
    logger_error = mocker.patch("country_workspace.notifications.tasks.logger.error")
    mocker.patch("country_workspace.notifications.tasks.get_notification_backend", return_value=backend)
    mocker.patch(
        "country_workspace.notifications.tasks.send_notification_event", side_effect=NotifyError("bad request")
    )

    send_bitcaster_event_task.run("data_imported", {"program_id": 12})
    logger_error.assert_called_once_with("Bitcaster send failed for event '%s': %s", "data_imported", "bad request")


def test_send_bitcaster_event_task_logs_warning_when_backend_returns_false(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    backend = Mock(is_configured=True)
    warning = mocker.patch("country_workspace.notifications.tasks.logger.warning")
    mocker.patch("country_workspace.notifications.tasks.get_notification_backend", return_value=backend)
    mocker.patch("country_workspace.notifications.tasks.send_notification_event", return_value=False)

    send_bitcaster_event_task.run("data_imported", {"program_id": 12})

    warning.assert_any_call("Bitcaster client returned false for event '%s'", "data_imported")


def test_send_bitcaster_event_task_skips_when_backend_not_configured(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    backend = Mock(is_configured=False)
    send_event = mocker.patch("country_workspace.notifications.tasks.send_notification_event")
    mocker.patch("country_workspace.notifications.tasks.get_notification_backend", return_value=backend)

    send_bitcaster_event_task.run("data_imported", {"program_id": 12})

    send_event.assert_not_called()


def test_send_bitcaster_event_task_skips_when_bitcaster_disabled(settings, mocker) -> None:
    _configure_bitcaster_settings(settings)
    settings.BITCASTER_ENABLED = False
    logger_info = mocker.patch("country_workspace.notifications.tasks.logger.info")
    get_backend = mocker.patch("country_workspace.notifications.tasks.get_notification_backend")

    send_bitcaster_event_task.run("data_imported", {"program_id": 12})

    logger_info.assert_called_once_with("Skipping Bitcaster task: integration disabled (event='%s').", "data_imported")
    get_backend.assert_not_called()
