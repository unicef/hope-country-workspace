from dataclasses import replace
from decimal import Decimal

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.biographic_dedup import BiographicSetState
from country_workspace.exceptions import RemoteError
from country_workspace.models import Program, Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.biographic.forms import BiographicDeduplicationConfigForm
from country_workspace.rdp.deduplication import workflow as dedup_workflow
from country_workspace.rdp.deduplication.types import ThresholdType
from country_workspace.rdp.operations import definitions
from country_workspace.rdp.push import workflow as push_workflow

pytestmark = pytest.mark.django_db


# --- definitions / dispatcher -------------------------------------------------


@pytest.mark.parametrize(("biometric", "biographic"), [(True, False), (False, True), (True, True), (False, False)])
def test_enabled_definitions(program, biometric: bool, biographic: bool) -> None:
    program.biometric_deduplication_enabled = biometric
    program.biographic_deduplication_enabled = biographic

    types = [d.operation_type for d in definitions.get_enabled_rdp_operation_definitions(program)]

    assert (RdpOperation.Type.BIOMETRIC_DEDUPLICATION in types) is biometric
    assert (RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION in types) is biographic


def test_biographic_form_prefix(program) -> None:
    program.biographic_deduplication_enabled = True

    [(definition, form)] = definitions.get_rdp_operation_forms(program=program)

    assert definition.operation_type == RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION
    assert isinstance(form, BiographicDeduplicationConfigForm)
    assert form.prefix == "biographic_deduplication"


def test_biographic_form_validates() -> None:
    form = BiographicDeduplicationConfigForm({"threshold_type": "count", "threshold_value": "3"})

    assert form.is_valid(), form.errors
    assert "individuals" in form.fields["threshold_type"].choices[0][1].lower()


@pytest.mark.parametrize(
    "operation_type",
    [RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION, RdpOperation.Type.BIOMETRIC_DEDUPLICATION],
)
def test_sync_rdp_operation_result_dispatches(rdp, mocker: MockerFixture, operation_type) -> None:
    from testutils.factories import BiographicRdpOperationFactory, BiometricRdpOperationFactory

    factory = (
        BiographicRdpOperationFactory
        if operation_type == RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION
        else BiometricRdpOperationFactory
    )
    operation = factory(rdp=rdp)
    sync = mocker.MagicMock(return_value=True)
    mocker.patch.dict(
        definitions.RDP_OPERATION_DEFINITIONS,
        {operation_type: replace(definitions.RDP_OPERATION_DEFINITIONS[operation_type], sync_result=sync)},
    )

    assert definitions.sync_rdp_operation_result(operation_id=operation.id) is True
    sync.assert_called_once_with(operation_id=operation.id)


def test_sync_rdp_operation_result_unknown_operation() -> None:
    from uuid import uuid4

    assert definitions.sync_rdp_operation_result(operation_id=uuid4()) is False


# --- push evaluation ----------------------------------------------------------


@pytest.mark.parametrize(
    ("exceeded", "status"),
    [(True, Rdp.PushStatus.REVIEW_PENDING), (False, Rdp.PushStatus.PUSH_PENDING)],
)
def test_evaluate_rdp_for_push_with_biographic_threshold(
    rdp: Rdp,
    successful_biographic_operation,
    mocker: MockerFixture,
    exceeded: bool,
    status: Rdp.PushStatus,
) -> None:
    successful_biographic_operation.config = {"threshold_type": "count", "threshold_value": "1"}
    mocker.patch.object(push_workflow, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(push_workflow, "has_incomplete_rdp_operations", return_value=False)
    mocker.patch.object(push_workflow, "biometric_operation_for_rdp", return_value=None)
    mocker.patch.object(push_workflow, "biographic_operation_for_rdp", return_value=successful_biographic_operation)
    mocker.patch.object(push_workflow, "biographic_findings_count", return_value=2)
    individuals = mocker.patch.object(push_workflow, "qs_individuals_for_rdp")
    individuals.return_value.count.return_value = 10
    threshold = mocker.patch.object(push_workflow, "threshold_exceeded", return_value=exceeded)
    mocker.patch.object(push_workflow, "append_rdp_log")
    schedule = mocker.patch.object(push_workflow, "_schedule_push_preparation")

    result = push_workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)

    assert result["outcome"] == status
    assert result["biographic_findings_count"] == 2
    assert result["biographic_findings_rate"] == "20.00"
    assert result["biographic_threshold_exceeded"] is exceeded
    assert "findings_count" not in result
    assert schedule.called is (not exceeded)
    threshold.assert_called_once_with(
        findings_count=2,
        total_count=10,
        threshold_type=ThresholdType.COUNT,
        threshold_value=Decimal(1),
    )


def test_evaluate_rdp_for_push_exceeds_when_either_operation_exceeds(
    rdp: Rdp,
    successful_biometric_operation,
    successful_biographic_operation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(push_workflow, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(push_workflow, "has_incomplete_rdp_operations", return_value=False)
    mocker.patch.object(push_workflow, "biometric_operation_for_rdp", return_value=successful_biometric_operation)
    mocker.patch.object(push_workflow, "biographic_operation_for_rdp", return_value=successful_biographic_operation)
    mocker.patch.object(push_workflow, "biometric_findings_count", return_value=0)
    mocker.patch.object(push_workflow, "biographic_findings_count", return_value=5)
    individuals = mocker.patch.object(push_workflow, "qs_individuals_for_rdp")
    individuals.return_value.count.return_value = 10
    mocker.patch.object(push_workflow, "threshold_exceeded", side_effect=[False, True])
    append = mocker.patch.object(push_workflow, "append_rdp_log")
    mocker.patch.object(push_workflow, "_schedule_push_preparation")

    result = push_workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)

    assert result["outcome"] == Rdp.PushStatus.REVIEW_PENDING
    assert result["findings_count"] == 0
    assert result["biographic_findings_count"] == 5
    assert append.call_args.kwargs["entry_type"] == RdpLogEntryType.REVIEW_REQUIRED


def test_evaluate_rdp_for_push_requires_individuals_with_biographic(
    rdp: Rdp, successful_biographic_operation, mocker: MockerFixture
) -> None:
    mocker.patch.object(push_workflow, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(push_workflow, "has_incomplete_rdp_operations", return_value=False)
    mocker.patch.object(push_workflow, "biometric_operation_for_rdp", return_value=None)
    mocker.patch.object(push_workflow, "biographic_operation_for_rdp", return_value=successful_biographic_operation)
    mocker.patch.object(push_workflow, "qs_individuals_for_rdp").return_value.count.return_value = 0

    with pytest.raises(RdpWorkflowError):
        push_workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)


def test_finish_successful_push_approves_biographic_set(
    push_pending_rdp: Rdp, biographic_operation, mocker: MockerFixture
) -> None:
    mocker.patch.object(push_workflow, "biometric_operation_for_rdp", return_value=None)
    mocker.patch.object(push_workflow, "biographic_operation_for_rdp", return_value=biographic_operation)
    mocker.patch.object(push_workflow, "set_rdp_beneficiaries_removed")
    mocker.patch.object(push_pending_rdp, "finish_push_attempt")
    on_commit = mocker.patch.object(push_workflow.transaction, "on_commit")

    push_workflow._finish_successful_push(rdp=push_pending_rdp, hope_rdi_id="RID")

    callbacks = [call.args[0] for call in on_commit.call_args_list]
    assert any(
        cb.func is push_workflow.approve_biographic_set_after_successful_push
        and cb.keywords["operation_id"] == biographic_operation.id
        for cb in callbacks
    )


# --- cancellation rejection ---------------------------------------------------


def _cancelled_job(rdp: Rdp, operation: RdpOperation, mocker: MockerFixture, **config):
    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    mocker.patch.object(dedup_workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(dedup_workflow, "biometric_operation_for_rdp", return_value=None)
    mocker.patch.object(dedup_workflow, "biographic_operation_for_rdp", return_value=operation)
    return mocker.MagicMock(config={"rdp_id": rdp.pk, "biographic_operation_id": str(operation.id), **config})


def test_reject_cancelled_rdp_rejects_deduplicated_biographic_set(
    rdp: Rdp, biographic_operation, mocker: MockerFixture
) -> None:
    job = _cancelled_job(rdp, biographic_operation, mocker)
    mocker.patch.object(dedup_workflow, "retrieve_biographic_set_state", return_value=BiographicSetState.DEDUPLICATED)
    reject = mocker.patch.object(dedup_workflow, "reject_biographic_set")

    assert dedup_workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}

    reject.assert_called_once_with(operation_id=biographic_operation.id)


@pytest.mark.parametrize(
    "state", [None, BiographicSetState.REJECTED, BiographicSetState.PENDING, BiographicSetState.FAILED]
)
def test_reject_cancelled_rdp_skips_non_blocking_biographic_set(
    rdp: Rdp, biographic_operation, mocker: MockerFixture, state
) -> None:
    job = _cancelled_job(rdp, biographic_operation, mocker)
    mocker.patch.object(dedup_workflow, "retrieve_biographic_set_state", return_value=state)
    reject = mocker.patch.object(dedup_workflow, "reject_biographic_set")

    assert dedup_workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}

    reject.assert_not_called()


def test_reject_cancelled_rdp_fails_for_blocking_biographic_state(
    rdp: Rdp, biographic_operation, mocker: MockerFixture
) -> None:
    job = _cancelled_job(rdp, biographic_operation, mocker)
    mocker.patch.object(dedup_workflow, "retrieve_biographic_set_state", return_value=BiographicSetState.INDEXING)

    with pytest.raises(RdpWorkflowError, match="can not reject"):
        dedup_workflow.reject_cancelled_rdp_set_core(job)


def test_reject_cancelled_rdp_wraps_remote_error(rdp: Rdp, biographic_operation, mocker: MockerFixture) -> None:
    job = _cancelled_job(rdp, biographic_operation, mocker)
    mocker.patch.object(dedup_workflow, "retrieve_biographic_set_state", return_value=BiographicSetState.DEDUPLICATED)
    mocker.patch.object(dedup_workflow, "reject_biographic_set", side_effect=RemoteError("boom"))

    with pytest.raises(RdpWorkflowError, match="boom"):
        dedup_workflow.reject_cancelled_rdp_set_core(job)


def test_reject_cancelled_rdp_stale_biographic_job(rdp: Rdp, biographic_operation, mocker: MockerFixture) -> None:
    job = _cancelled_job(rdp, biographic_operation, mocker, biographic_operation_id="other")

    with pytest.raises(RdpWorkflowError, match="no longer current"):
        dedup_workflow.reject_cancelled_rdp_set_core(job)


@pytest.mark.parametrize("biographic", [None, "op-id"])
def test_schedule_cancelled_rdp_set_rejection_config(rdp: Rdp, mocker: MockerFixture, biographic: str | None) -> None:
    mocker.patch.object(dedup_workflow.transaction, "on_commit")

    job = dedup_workflow.schedule_cancelled_rdp_set_rejection(
        rdp=rdp, user_id=rdp.pushed_by_id, biographic_operation_id=biographic
    )

    assert ("biographic_operation_id" in job.config) is (biographic is not None)
    assert "deduplication_set_id" not in job.config
    assert Program.objects.filter(pk=rdp.program_id).exists()
