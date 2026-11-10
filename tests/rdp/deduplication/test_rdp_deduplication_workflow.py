from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Program, Rdp, RdpOperation
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication import workflow
from country_workspace.rdp.deduplication.backend import DeduplicationBackend, RejectionDecision
from country_workspace.rdp.policy import ActionCheck

pytestmark = pytest.mark.django_db


@pytest.fixture
def operations(rdp: Rdp, biometric_operation: RdpOperation, biographic_operation: RdpOperation) -> list[RdpOperation]:
    """Biographic comes before biometric: operations are ordered by type."""
    return [biographic_operation, biometric_operation]


@pytest.fixture
def backends(mocker: MockerFixture) -> dict[str, DeduplicationBackend]:
    """Replace the DedupEngine implementations with mocks."""
    fakes = {
        operation_type.value: DeduplicationBackend(
            operation_type=operation_type,
            sync=mocker.Mock(return_value=True),
            check_cancellation=mocker.Mock(return_value=RejectionDecision(ActionCheck(True))),
            check_clean=mocker.Mock(return_value=ActionCheck(True)),
            reject=mocker.Mock(),
            approve=mocker.Mock(),
        )
        for operation_type in (
            RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
            RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION,
        )
    }
    mocker.patch.object(workflow, "get_deduplication_backends", return_value=fakes)
    mocker.patch.object(workflow, "get_deduplication_backend", side_effect=lambda op: fakes.get(op.operation_type))
    return fakes


def test_deduplication_operations_for_rdp(
    rdp: Rdp, operations: list[RdpOperation], ocr_operation: RdpOperation
) -> None:
    assert workflow.deduplication_operations_for_rdp(rdp) == operations


def test_sync_deduplication_result_missing_operation() -> None:
    assert workflow.sync_deduplication_result(operation_id=uuid4()) is False


def test_sync_deduplication_result_ignores_other_operation_types(
    ocr_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
) -> None:
    assert workflow.sync_deduplication_result(operation_id=ocr_operation.id) is False

    assert all(not backend.sync.called for backend in backends.values())


@pytest.mark.parametrize("operation_type", ["biometric_operation", "biographic_operation"])
def test_sync_deduplication_result_dispatches_to_backend(
    request: pytest.FixtureRequest,
    backends: dict[str, DeduplicationBackend],
    operation_type: str,
) -> None:
    operation: RdpOperation = request.getfixturevalue(operation_type)

    assert workflow.sync_deduplication_result(operation_id=operation.id) is True

    backends[operation.operation_type].sync.assert_called_once()
    assert backends[operation.operation_type].sync.call_args.args[0].pk == operation.pk
    assert [b.sync.called for b in backends.values()].count(True) == 1


def test_check_cancellation_rejections_without_operations(rdp: Rdp, backends: dict[str, DeduplicationBackend]) -> None:
    check, operation_ids = workflow.check_cancellation_rejections(rdp)

    assert check.allowed
    assert operation_ids == ()


def test_check_cancellation_rejections_returns_required_operations(
    rdp: Rdp,
    operations: list[RdpOperation],
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    biographic, biometric = operations
    backends[biographic.operation_type].check_cancellation.return_value = RejectionDecision(
        ActionCheck(True), required=True
    )

    check, operation_ids = workflow.check_cancellation_rejections(rdp)

    assert check.allowed
    assert operation_ids == (biographic.id,)
    backends[biometric.operation_type].check_cancellation.assert_called_once()


def test_check_cancellation_rejections_blocks_on_first_denial(
    rdp: Rdp,
    operations: list[RdpOperation],
    backends: dict[str, DeduplicationBackend],
) -> None:
    biographic, biometric = operations
    denied = ActionCheck(False, "busy")
    backends[biographic.operation_type].check_cancellation.return_value = RejectionDecision(
        ActionCheck(True), required=True
    )
    backends[biometric.operation_type].check_cancellation.return_value = RejectionDecision(denied)

    assert workflow.check_cancellation_rejections(rdp) == (denied, ())


def test_check_clean_rdp_deduplication(
    rdp: Rdp,
    operations: list[RdpOperation],
    backends: dict[str, DeduplicationBackend],
) -> None:
    check, checked = workflow.check_clean_rdp_deduplication(rdp)

    assert check.allowed
    assert list(checked) == operations


def test_check_clean_rdp_deduplication_without_operations(
    rdp: Rdp,
    backends: dict[str, DeduplicationBackend],
) -> None:
    assert workflow.check_clean_rdp_deduplication(rdp) == (ActionCheck(True), ())


def test_check_clean_rdp_deduplication_stops_on_denial(
    rdp: Rdp,
    operations: list[RdpOperation],
    backends: dict[str, DeduplicationBackend],
) -> None:
    denied = ActionCheck(False, "wrong state")
    backends[operations[0].operation_type].check_clean.return_value = denied

    assert workflow.check_clean_rdp_deduplication(rdp) == (denied, ())
    backends[operations[1].operation_type].check_clean.assert_not_called()


def _cancel(rdp: Rdp) -> None:
    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])


def test_reject_cancelled_rdp_set_core_rejects_every_operation(
    rdp: Rdp,
    operations: list[RdpOperation],
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    _cancel(rdp)
    job = mocker.MagicMock(config={"rdp_id": rdp.pk, "operation_ids": [str(op.id) for op in operations]})

    assert workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}

    for operation in operations:
        backends[operation.operation_type].reject.assert_called_once()
        assert backends[operation.operation_type].reject.call_args.args[0].pk == operation.pk


def test_reject_cancelled_rdp_set_core_rejects_only_scheduled_operations(
    rdp: Rdp,
    operations: list[RdpOperation],
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    _cancel(rdp)
    biographic, biometric = operations
    job = mocker.MagicMock(config={"rdp_id": rdp.pk, "operation_ids": [str(biometric.id)]})

    workflow.reject_cancelled_rdp_set_core(job)

    backends[biometric.operation_type].reject.assert_called_once()
    backends[biographic.operation_type].reject.assert_not_called()


def test_reject_cancelled_rdp_set_core_accepts_legacy_job_config(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    _cancel(rdp)
    job = mocker.MagicMock(config={"rdp_id": rdp.pk, "deduplication_set_id": str(biometric_operation.id)})

    workflow.reject_cancelled_rdp_set_core(job)

    backends[biometric_operation.operation_type].reject.assert_called_once()


def test_reject_cancelled_rdp_set_core_rejects_stale_job_for_active_rdp(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(config={"rdp_id": rdp.pk, "operation_ids": [str(biometric_operation.id)]})

    with pytest.raises(RdpWorkflowError, match="no longer current"):
        workflow.reject_cancelled_rdp_set_core(job)

    backends[biometric_operation.operation_type].reject.assert_not_called()


def test_reject_cancelled_rdp_set_core_rejects_stale_job_for_unknown_operation(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    _cancel(rdp)
    job = mocker.MagicMock(config={"rdp_id": rdp.pk, "operation_ids": [str(uuid4())]})

    with pytest.raises(RdpWorkflowError, match="no longer current"):
        workflow.reject_cancelled_rdp_set_core(job)


def test_reject_cancelled_rdp_set_core_propagates_backend_errors(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    _cancel(rdp)
    backends[biometric_operation.operation_type].reject.side_effect = RdpWorkflowError({"errors": ["boom"]})
    schedule = mocker.patch.object(workflow, "schedule_rdp_operations")
    job = mocker.MagicMock(config={"rdp_id": rdp.pk, "operation_ids": [str(biometric_operation.id)], "clean_rdp_id": 1})

    with pytest.raises(RdpWorkflowError, match="boom"):
        workflow.reject_cancelled_rdp_set_core(job)

    schedule.assert_not_called()


def test_reject_cancelled_rdp_set_core_schedules_clean_rdp(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    from testutils.factories import RdpFactory

    _cancel(rdp)
    clean_rdp = RdpFactory(program=rdp.program)
    schedule = mocker.patch.object(workflow, "schedule_rdp_operations")
    job = mocker.MagicMock(
        config={"rdp_id": rdp.pk, "operation_ids": [str(biometric_operation.id)], "clean_rdp_id": clean_rdp.pk}
    )

    assert workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}

    schedule.assert_called_once_with(rdp=clean_rdp)


def test_reject_cancelled_rdp_set_core_skips_clean_rdp_during_program_cleanup(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    from testutils.factories import RdpFactory

    _cancel(rdp)
    clean_rdp = RdpFactory(program=rdp.program)
    Program.objects.filter(pk=rdp.program_id).update(cleanup_in_progress=True)
    schedule = mocker.patch.object(workflow, "schedule_rdp_operations")
    job = mocker.MagicMock(
        config={"rdp_id": rdp.pk, "operation_ids": [str(biometric_operation.id)], "clean_rdp_id": clean_rdp.pk}
    )

    assert workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}

    backends[biometric_operation.operation_type].reject.assert_called_once()
    schedule.assert_not_called()


def test_reject_cancelled_rdp_set_core_rejects_non_pending_clean_rdp(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    from testutils.factories import RdpFactory

    _cancel(rdp)
    clean_rdp = RdpFactory(program=rdp.program, status=Rdp.PushStatus.CANCELLED)
    job = mocker.MagicMock(
        config={"rdp_id": rdp.pk, "operation_ids": [str(biometric_operation.id)], "clean_rdp_id": clean_rdp.pk}
    )

    with pytest.raises(RdpWorkflowError, match="clean replacement"):
        workflow.reject_cancelled_rdp_set_core(job)


def test_schedule_cancelled_rdp_set_rejection(rdp: Rdp, user, mocker: MockerFixture) -> None:
    job = mocker.MagicMock()
    create = mocker.patch.object(workflow.AsyncJob.objects, "create", return_value=job)
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")
    first, second = uuid4(), uuid4()

    assert (
        workflow.schedule_cancelled_rdp_set_rejection(
            rdp=rdp,
            user_id=user.pk,
            operation_ids=(second, first),
            clean_rdp_id=123,
        )
        is job
    )

    assert create.call_args.kwargs["config"] == {
        "rdp_id": rdp.pk,
        "operation_ids": sorted([str(first), str(second)]),
        "clean_rdp_id": 123,
    }
    assert (
        create.call_args.kwargs["action"]
        == "country_workspace.rdp.deduplication.workflow.reject_cancelled_rdp_set_core"
    )
    on_commit.assert_called_once_with(job.queue, robust=True)


def test_schedule_cancelled_rdp_set_rejection_without_clean_rdp(rdp: Rdp, user, mocker: MockerFixture) -> None:
    create = mocker.patch.object(workflow.AsyncJob.objects, "create")
    mocker.patch.object(workflow.transaction, "on_commit")
    operation_id = uuid4()

    workflow.schedule_cancelled_rdp_set_rejection(rdp=rdp, user_id=user.pk, operation_ids=[operation_id])

    assert create.call_args.kwargs["config"] == {"rdp_id": rdp.pk, "operation_ids": [str(operation_id)]}


def test_schedule_deduplication_approval_without_operations(
    rdp: Rdp,
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    workflow.schedule_deduplication_approval(rdp)

    on_commit.assert_not_called()


def test_schedule_deduplication_approval_approves_every_operation_after_commit(
    rdp: Rdp,
    operations: list[RdpOperation],
    backends: dict[str, DeduplicationBackend],
    mocker: MockerFixture,
) -> None:
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    workflow.schedule_deduplication_approval(rdp)

    on_commit.assert_called_once()
    callback = on_commit.call_args.args[0]
    assert on_commit.call_args.kwargs == {"robust": True}
    for backend in backends.values():
        backend.approve.assert_not_called()

    callback()

    for operation in operations:
        backends[operation.operation_type].approve.assert_called_once()
        assert backends[operation.operation_type].approve.call_args.args[0].pk == operation.pk
