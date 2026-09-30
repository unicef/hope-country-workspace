import pytest
from pytest_mock import MockerFixture

from country_workspace.rdp.operations import completion
from typing import TYPE_CHECKING

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


def test_complete_rdp_operation(
    running_biometric_operation,
    mocker: MockerFixture,
) -> None:
    findings: list[RdpOperationFinding] = []
    mocker.patch.object(completion, "finish_rdp_operation", return_value=True)
    schedule = mocker.patch.object(completion, "schedule_rdp_push_evaluation")

    assert (
        completion.complete_rdp_operation(
            operation=running_biometric_operation,
            findings=findings,
        )
        is True
    )

    schedule.assert_called_once_with(rdp=running_biometric_operation.rdp)


def test_complete_rdp_operation_marks_failure_on_error(
    running_biometric_operation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(completion, "finish_rdp_operation", return_value=True)
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
