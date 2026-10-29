import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Rdp, RdpOperation, User
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


def test_run_rdp_operation_core_records_runner_error(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(config={"operation_id": str(biometric_operation.id)})
    mocker.patch.object(workflow, "claim_rdp_operation", return_value=biometric_operation)
    definition = mocker.MagicMock()
    error = RuntimeError("failed")
    definition.runner.side_effect = error
    mocker.patch.dict(
        definitions.RDP_OPERATION_DEFINITIONS,
        {biometric_operation.operation_type: definition},
        clear=True,
    )
    handle_error = mocker.patch.object(workflow, "handle_rdp_operation_error")

    with pytest.raises(RuntimeError, match="failed"):
        workflow.run_rdp_operation_core(job)

    handle_error.assert_called_once_with(operation=biometric_operation, exc=error)


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


def test_has_retryable_rdp_operations_for_failed_operation(
    rdp: Rdp,
    failed_biometric_operation: RdpOperation,
) -> None:
    assert workflow.has_retryable_rdp_operations(rdp_id=rdp.pk) is True


def test_retry_rdp_operations_retries_failed_operation(
    rdp: Rdp,
    failed_biometric_operation: RdpOperation,
    user: User,
    mocker: MockerFixture,
) -> None:
    fail = mocker.patch.object(workflow, "fail_rdp_operation")
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert workflow.retry_rdp_operations(rdp_id=rdp.pk, owner_id=user.pk) == 1

    fail.assert_not_called()
    schedule.assert_called_once_with(operation=failed_biometric_operation, owner_id=user.pk)


def test_retry_rdp_operations_prefers_failed_operations(
    rdp: Rdp,
    failed_biometric_operation: RdpOperation,
    user: User,
    mocker: MockerFixture,
) -> None:
    ocr_operation = RdpOperation.objects.create(
        rdp=rdp,
        operation_type=RdpOperation.Type.OCR,
        status=RdpOperation.Status.RUNNING,
        attempt=1,
    )
    fail = mocker.patch.object(workflow, "fail_rdp_operation")
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert workflow.retry_rdp_operations(rdp_id=rdp.pk, owner_id=user.pk) == 1

    fail.assert_not_called()
    schedule.assert_called_once_with(operation=failed_biometric_operation, owner_id=user.pk)

    ocr_operation.refresh_from_db()
    assert ocr_operation.status == RdpOperation.Status.RUNNING


def test_retry_rdp_operations_restarts_running_ocr(
    rdp: Rdp,
    user: User,
    mocker: MockerFixture,
) -> None:
    operation = RdpOperation.objects.create(
        rdp=rdp,
        operation_type=RdpOperation.Type.OCR,
        status=RdpOperation.Status.RUNNING,
        attempt=2,
    )
    fail = mocker.patch.object(workflow, "fail_rdp_operation", return_value=True)
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert workflow.has_retryable_rdp_operations(rdp_id=rdp.pk) is True
    assert workflow.retry_rdp_operations(rdp_id=rdp.pk, owner_id=user.pk) == 1

    fail.assert_called_once_with(
        operation_id=operation.id,
        expected_attempt=2,
        error={"message": "Operation manually restarted while still running."},
    )
    schedule.assert_called_once_with(operation=operation, owner_id=user.pk)


def test_retry_rdp_operations_skips_running_operation_if_fail_is_stale(
    running_ocr_operation: RdpOperation,
    user: User,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "fail_rdp_operation", return_value=False)
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert workflow.retry_rdp_operations(rdp_id=running_ocr_operation.rdp_id, owner_id=user.pk) == 0
    schedule.assert_not_called()


def test_running_biometric_operation_is_not_retryable(
    rdp: Rdp,
    running_biometric_operation: RdpOperation,
    user: User,
    mocker: MockerFixture,
) -> None:
    fail = mocker.patch.object(workflow, "fail_rdp_operation")
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert workflow.has_retryable_rdp_operations(rdp_id=rdp.pk) is False
    assert workflow.retry_rdp_operations(rdp_id=rdp.pk, owner_id=user.pk) == 0

    fail.assert_not_called()
    schedule.assert_not_called()


def test_retry_rdp_operations_ignores_non_pending_rdp(
    rdp: Rdp,
    failed_biometric_operation: RdpOperation,
    user: User,
    mocker: MockerFixture,
) -> None:
    rdp.status = Rdp.PushStatus.SUCCESS
    rdp.save(update_fields=["status"])
    fail = mocker.patch.object(workflow, "fail_rdp_operation")
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert workflow.retry_rdp_operations(rdp_id=rdp.pk, owner_id=user.pk) == 0

    fail.assert_not_called()
    schedule.assert_not_called()


def test_retry_rdp_operations_during_program_cleanup(
    rdp: Rdp,
    failed_biometric_operation: RdpOperation,
    user: User,
    mocker: MockerFixture,
) -> None:
    rdp.program.cleanup_in_progress = True
    rdp.program.save(update_fields=["cleanup_in_progress"])
    fail = mocker.patch.object(workflow, "fail_rdp_operation")
    schedule = mocker.patch.object(workflow, "schedule_rdp_operation")

    assert workflow.retry_rdp_operations(rdp_id=rdp.pk, owner_id=user.pk) is None

    fail.assert_not_called()
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
