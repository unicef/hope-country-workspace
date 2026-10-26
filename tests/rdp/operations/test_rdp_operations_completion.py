from typing import TYPE_CHECKING

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation
from country_workspace.rdp.operations import completion

if TYPE_CHECKING:
    from country_workspace.models import RdpOperationFinding


pytestmark = pytest.mark.django_db


def test_complete_rdp_operation_not_finished(
    running_biometric_operation,
    mocker: MockerFixture,
) -> None:
    findings: list[RdpOperationFinding] = []
    finish = mocker.patch.object(completion, "finish_rdp_operation", return_value=False)
    schedule = mocker.patch.object(completion, "schedule_rdp_push_evaluation")

    assert (
        completion.complete_rdp_operation(
            operation=running_biometric_operation,
            findings=findings,
        )
        is False
    )

    finish.assert_called_once_with(
        operation_id=running_biometric_operation.id,
        findings=findings,
        expected_attempt=running_biometric_operation.attempt,
    )
    schedule.assert_not_called()


@pytest.mark.parametrize("incomplete", [True, False])
def test_complete_rdp_operation_schedules_evaluation_when_operations_complete(
    running_biometric_operation,
    mocker: MockerFixture,
    incomplete: bool,
) -> None:
    findings: list[RdpOperationFinding] = []
    mocker.patch.object(completion, "finish_rdp_operation", return_value=True)
    rdp = running_biometric_operation.rdp
    mocker.patch.object(completion, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(completion, "has_incomplete_rdp_operations", return_value=incomplete)
    schedule = mocker.patch.object(completion, "schedule_rdp_push_evaluation")

    assert completion.complete_rdp_operation(
        operation=running_biometric_operation,
        findings=findings,
    )

    assert schedule.called is not incomplete


def test_complete_rdp_operation_records_error(
    running_biometric_operation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(completion, "finish_rdp_operation", return_value=True)
    mocker.patch.object(completion, "has_incomplete_rdp_operations", return_value=False)
    mocker.patch.object(
        completion,
        "lock_rdp_for_update",
        return_value=running_biometric_operation.rdp,
    )
    error = RuntimeError("failed")
    mocker.patch.object(completion, "schedule_rdp_push_evaluation", side_effect=error)
    handle_error = mocker.patch.object(completion, "handle_rdp_operation_error")

    with pytest.raises(RuntimeError, match="failed"):
        completion.complete_rdp_operation(
            operation=running_biometric_operation,
            findings=[],
        )

    handle_error.assert_called_once_with(operation=running_biometric_operation, exc=error)


@pytest.mark.parametrize(
    ("outcome", "fails", "completes"),
    [
        (None, False, False),
        (RdpOperation.Status.FAILURE, True, False),
        (RdpOperation.Status.SUCCESS, False, True),
    ],
)
def test_finalize_rdp_operation_from_units(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
    outcome: RdpOperation.Status | None,
    fails: bool,
    completes: bool,
) -> None:
    lock = mocker.patch.object(completion, "lock_current_rdp_operation", return_value=running_ocr_operation)
    mocker.patch.object(completion, "get_rdp_operation_units_outcome", return_value=outcome)
    fail = mocker.patch.object(completion, "fail_rdp_operation", return_value=True)
    complete = mocker.patch.object(completion, "complete_rdp_operation", return_value=True)

    assert completion.finalize_rdp_operation_from_units(operation=running_ocr_operation) is (outcome is not None)

    lock.assert_called_once_with(
        operation_id=running_ocr_operation.id,
        expected_attempt=running_ocr_operation.attempt,
    )
    assert fail.called is fails
    assert complete.called is completes


def test_finalize_rdp_operation_from_units_ignores_stale_attempt(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(completion, "lock_current_rdp_operation", return_value=None)
    outcome = mocker.patch.object(completion, "get_rdp_operation_units_outcome")

    assert completion.finalize_rdp_operation_from_units(operation=running_ocr_operation) is False
    outcome.assert_not_called()
