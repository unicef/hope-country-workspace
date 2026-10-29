import pytest
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation
from country_workspace.rdp.operations import errors


pytestmark = pytest.mark.django_db


def test_handle_rdp_operation_error(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    record = mocker.patch.object(errors, "record_rdp_operation_error")
    exc = RuntimeError("failed")

    errors.handle_rdp_operation_error(operation=running_ocr_operation, exc=exc)

    record.assert_called_once_with(
        operation_id=running_ocr_operation.id,
        expected_attempt=running_ocr_operation.attempt,
        error={"message": "failed"},
    )


def test_handle_rdp_operation_error_logs_persistence_failure(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(errors, "record_rdp_operation_error", side_effect=RuntimeError("db failed"))
    log = mocker.patch.object(errors.logger, "exception")

    errors.handle_rdp_operation_error(operation=running_ocr_operation, exc=RuntimeError("failed"))

    log.assert_called_once()
