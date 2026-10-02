from typing import TYPE_CHECKING

import pytest
from pytest_mock import MockerFixture

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

    finish.assert_called_once_with(operation_id=running_biometric_operation.id, findings=findings)
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
    lock = mocker.patch.object(completion, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(completion, "has_incomplete_rdp_operations", return_value=incomplete)
    schedule = mocker.patch.object(completion, "schedule_rdp_push_evaluation")

    assert completion.complete_rdp_operation(
        operation=running_biometric_operation,
        findings=findings,
    )

    lock.assert_called_once_with(pk=running_biometric_operation.rdp_id)
    assert schedule.called is not incomplete


def test_complete_rdp_operation_marks_failure_on_error(
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
    mocker.patch.object(
        completion,
        "schedule_rdp_push_evaluation",
        side_effect=RuntimeError("failed"),
    )
    fail = mocker.patch.object(completion, "fail_rdp_operation")

    with pytest.raises(RuntimeError, match="failed"):
        completion.complete_rdp_operation(
            operation=running_biometric_operation,
            findings=[],
        )

    fail.assert_called_once()
    assert "failed" in fail.call_args.kwargs["error"]["message"]
