import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Rdp, RdpOperation
from country_workspace.rdp.operations import definitions, workflow


pytestmark = pytest.mark.django_db


def test_run_rdp_operation_core_not_claimed(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={"operation_id": str(biometric_operation.id)},
    )
    mocker.patch.object(workflow, "claim_rdp_operation", return_value=None)

    assert workflow.run_rdp_operation_core(job) == {
        "operation_id": str(biometric_operation.id),
        "started": False,
    }


def test_run_rdp_operation_core(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={"operation_id": str(biometric_operation.id)},
    )
    mocker.patch.object(workflow, "claim_rdp_operation", return_value=biometric_operation)
    definition = mocker.MagicMock()
    mocker.patch.dict(
        definitions.RDP_OPERATION_DEFINITIONS,
        {biometric_operation.operation_type: definition},
        clear=True,
    )

    assert workflow.run_rdp_operation_core(job) == {
        "operation_id": str(biometric_operation.id),
        "started": True,
    }

    definition.runner.assert_called_once_with(biometric_operation)


def test_run_rdp_operation_core_rejects_unsupported_operation(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    biometric_operation.operation_type = "UNKNOWN"
    job = mocker.MagicMock(
        config={"operation_id": str(biometric_operation.id)},
    )
    mocker.patch.object(workflow, "claim_rdp_operation", return_value=biometric_operation)
    fail = mocker.patch.object(workflow, "fail_rdp_operation")

    with pytest.raises(ValueError, match="Unsupported RDP operation type"):
        workflow.run_rdp_operation_core(job)

    fail.assert_called_once()
    assert "Unsupported" in fail.call_args.kwargs["error"]["message"]


def test_run_rdp_operation_core_marks_failure_on_runner_error(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={"operation_id": str(biometric_operation.id)},
    )
    mocker.patch.object(workflow, "claim_rdp_operation", return_value=biometric_operation)
    definition = mocker.MagicMock()
    definition.runner.side_effect = RuntimeError("failed")
    mocker.patch.dict(
        definitions.RDP_OPERATION_DEFINITIONS,
        {biometric_operation.operation_type: definition},
        clear=True,
    )
    fail = mocker.patch.object(workflow, "fail_rdp_operation")

    with pytest.raises(RuntimeError, match="failed"):
        workflow.run_rdp_operation_core(job)

    fail.assert_called_once()
    assert "failed" in fail.call_args.kwargs["error"]["message"]


def test_schedule_rdp_operation(
    biometric_operation: RdpOperation,
    user,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock()
    create = mocker.patch.object(workflow.AsyncJob.objects, "create", return_value=job)
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    assert (
        workflow.schedule_rdp_operation(
            operation=biometric_operation,
            owner_id=user.pk,
        )
        is job
    )

    kwargs = create.call_args.kwargs
    assert kwargs["owner_id"] == user.pk
    assert kwargs["program_id"] == biometric_operation.rdp.program_id
    assert kwargs["rdp_id"] == biometric_operation.rdp_id
    assert kwargs["config"] == {"operation_id": str(biometric_operation.id)}
    assert kwargs["action"] == workflow.fqn(workflow.run_rdp_operation_core)
    on_commit.assert_called_once_with(job.queue, robust=True)


def test_retry_failed_rdp_operations(
    rdp: Rdp,
    failed_biometric_operation: RdpOperation,
    user,
    mocker: MockerFixture,
) -> None:
    failed = mocker.patch.object(
        workflow,
        "failed_rdp_operations",
        return_value=[failed_biometric_operation],
    )
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert (
        workflow.retry_failed_rdp_operations(
            rdp_id=rdp.pk,
            owner_id=user.pk,
        )
        == 1
    )

    failed.assert_called_once_with(rdp_id=rdp.pk)
    schedule.assert_called_once_with(
        operation=failed_biometric_operation,
        owner_id=user.pk,
    )


def test_retry_failed_rdp_operations_ignores_non_pending_rdp(
    rdp: Rdp,
    user,
    mocker: MockerFixture,
) -> None:
    rdp.status = Rdp.PushStatus.SUCCESS
    rdp.save(update_fields=["status"])
    failed = mocker.patch.object(workflow, "failed_rdp_operations")
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert (
        workflow.retry_failed_rdp_operations(
            rdp_id=rdp.pk,
            owner_id=user.pk,
        )
        == 0
    )

    failed.assert_not_called()
    schedule.assert_not_called()


def test_schedule_rdp_operations(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    workflow.schedule_rdp_operations(rdp=rdp)

    schedule.assert_called_once_with(
        operation=biometric_operation,
        owner_id=rdp.pushed_by_id,
    )
