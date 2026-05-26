from country_workspace.notifications.handlers import (
    handle_data_imported,
    handle_rdi_pushed,
    handle_rdp_pushed,
    handle_validation_completed,
)


def test_handle_data_imported_enqueues_expected_event_and_payload(mocker) -> None:
    delay = mocker.patch("country_workspace.notifications.handlers.send_bitcaster_event_task.delay")

    handle_data_imported(
        sender=object(),
        program_id=10,
        batch_id=20,
        record_count=30,
        source="KOBO",
    )

    delay.assert_called_once_with(
        "data_imported",
        {
            "program_id": 10,
            "batch_id": 20,
            "record_count": 30,
            "source": "KOBO",
        },
    )


def test_handle_validation_completed_enqueues_expected_event_and_payload(mocker) -> None:
    delay = mocker.patch("country_workspace.notifications.handlers.send_bitcaster_event_task.delay")

    handle_validation_completed(
        sender=object(),
        program_id=10,
        context="rdi",
        results={"valid": 3, "invalid": 1},
    )

    delay.assert_called_once_with(
        "validation_completed",
        {
            "program_id": 10,
            "context": "rdi",
            "results": {"valid": 3, "invalid": 1},
        },
    )


def test_handle_rdi_pushed_enqueues_expected_event_and_payload(mocker) -> None:
    delay = mocker.patch("country_workspace.notifications.handlers.send_bitcaster_event_task.delay")

    handle_rdi_pushed(
        sender=object(),
        program_id=44,
        target="HOPE",
        pushed_count=77,
    )

    delay.assert_called_once_with(
        "rdi_pushed",
        {
            "program_id": 44,
            "target": "HOPE",
            "pushed_count": 77,
        },
    )


def test_handle_rdp_pushed_enqueues_expected_event_and_payload(mocker) -> None:
    delay = mocker.patch("country_workspace.notifications.handlers.send_bitcaster_event_task.delay")

    handle_rdp_pushed(
        sender=object(),
        program_id=55,
        rdp_id=66,
        status="FAILURE",
    )

    delay.assert_called_once_with(
        "rdp_pushed",
        {
            "program_id": 55,
            "rdp_id": 66,
            "status": "FAILURE",
        },
    )
