from decimal import Decimal
from uuid import uuid4

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.rdi import HopeRdiResetUnconfirmedError, RdiResetResult
from country_workspace.models import Rdp
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.deduplication.types import ThresholdType
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.push import workflow
from country_workspace.rdp.types import RdpWorkflowOutcome


pytestmark = pytest.mark.django_db


def test_push_callback_helpers(mocker: MockerFixture) -> None:
    reverse = mocker.patch.object(workflow, "reverse", return_value="/callback/")
    dumps = mocker.patch.object(workflow.signing, "dumps", return_value="TOKEN")
    push_attempt_id = uuid4()

    with override_config(APP_BASE_URL="https://example.org/"):
        assert workflow._build_push_ready_callback_url() == "https://example.org/callback/"

    assert workflow._build_push_ready_callback_token(rdp_id=12, push_attempt_id=push_attempt_id) == "TOKEN"

    reverse.assert_called_once_with("api:callbacks:hope-rdp-push-ready")
    dumps.assert_called_once_with(
        {"rdp_id": 12, "push_attempt_id": str(push_attempt_id)},
        salt=workflow.PUSH_READY_CALLBACK_SALT,
    )


@pytest.mark.parametrize("with_operation", [True, False])
def test_country_workspace_id_for_rdp(
    rdp: Rdp,
    biometric_operation,
    mocker: MockerFixture,
    with_operation: bool,
) -> None:
    mocker.patch.object(
        workflow,
        "biometric_operation_for_rdp",
        return_value=biometric_operation if with_operation else None,
    )

    expected = str(biometric_operation.id) if with_operation else f"rdp-{rdp.pk}"

    assert workflow._country_workspace_id_for_rdp(rdp) == expected


def test_workflow_config_for_rdp(
    rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "rdp_selection", return_value=(False, [1, 2]))
    mocker.patch.object(workflow, "_country_workspace_id_for_rdp", return_value="CW")

    assert workflow._workflow_config_for_rdp(
        rdp=rdp,
        imported_by_email="user@example.com",
    ) == {
        "batch_name": rdp.name,
        "co_slug": rdp.program.country_office.slug,
        "country_workspace_id": "CW",
        "imported_by_email": "user@example.com",
        "master_detail": False,
        "pks": [1, 2],
        "program_hope_id": rdp.program.hope_id,
        "rdp_id": rdp.pk,
    }


def test_fail_pending_push_ignores_stale_attempt(
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=None)
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    workflow._fail_pending_push(
        rdp_id=1,
        push_attempt_id=uuid4(),
        hope_rdi_id="RID",
    )

    on_commit.assert_not_called()


@pytest.mark.parametrize(
    ("current_rdi_id", "fallback_rdi_id", "expected"),
    [
        ("CURRENT", "FALLBACK", "CURRENT"),
        ("N/A", "FALLBACK", "FALLBACK"),
        (None, None, "N/A"),
    ],
)
def test_fail_pending_push(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
    current_rdi_id: str | None,
    fallback_rdi_id: str | None,
    expected: str,
) -> None:
    push_pending_rdp.hope_rdi_id = current_rdi_id
    finish = mocker.patch.object(push_pending_rdp, "finish_push_attempt")
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=push_pending_rdp)
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    workflow._fail_pending_push(
        rdp_id=push_pending_rdp.pk,
        push_attempt_id=push_pending_rdp.push_attempt_id,
        hope_rdi_id=fallback_rdi_id,
    )

    finish.assert_called_once_with(status=Rdp.PushStatus.FAILURE, hope_rdi_id=expected)
    assert on_commit.call_args.kwargs["robust"] is True


def test_schedule_push_data_ignores_stale_attempt(mocker: MockerFixture) -> None:
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=None)

    assert workflow._schedule_push_data(rdp_id=1, push_attempt_id=uuid4()) is None


@pytest.mark.parametrize(
    ("created", "hope_rdi_id", "scheduled"),
    [
        (True, "OLD", True),
        (False, None, True),
        (False, "RID", False),
    ],
)
def test_schedule_push_data(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
    created: bool,
    hope_rdi_id: str | None,
    scheduled: bool,
) -> None:
    push_pending_rdp.hope_rdi_id = hope_rdi_id
    push_pending_rdp.save(update_fields=["hope_rdi_id"])
    job = mocker.MagicMock()
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=push_pending_rdp)
    mocker.patch.object(workflow, "get_or_create_rdp_push_data_job", return_value=(job, created))
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    result = workflow._schedule_push_data(
        rdp_id=push_pending_rdp.pk,
        push_attempt_id=push_pending_rdp.push_attempt_id,
    )

    assert (result is job) is scheduled
    assert on_commit.called is scheduled
    if created:
        push_pending_rdp.refresh_from_db()
        assert push_pending_rdp.hope_rdi_id is None


def test_schedule_push_preparation_requires_attempt(rdp: Rdp) -> None:
    with pytest.raises(RuntimeError, match="not initialized"):
        workflow._schedule_push_preparation(rdp=rdp, user_id=1)


@pytest.mark.parametrize(
    ("hope_rdi_id", "expected_reset"),
    [("RID", "RID"), ("N/A", None)],
)
def test_schedule_push_preparation(
    push_pending_rdp: Rdp,
    user,
    mocker: MockerFixture,
    hope_rdi_id: str,
    expected_reset: str | None,
) -> None:
    push_pending_rdp.hope_rdi_id = hope_rdi_id
    job = mocker.MagicMock()
    create = mocker.patch.object(workflow.AsyncJob.objects, "create", return_value=job)
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    workflow._schedule_push_preparation(rdp=push_pending_rdp, user_id=user.pk)

    assert create.call_args.kwargs["config"] == {
        "rdp_id": push_pending_rdp.pk,
        "push_attempt_id": str(push_pending_rdp.push_attempt_id),
        "rdi_id_to_reset": expected_reset,
    }
    on_commit.assert_called_once_with(job.queue, robust=True)


def test_evaluate_rdp_for_push_ignores_non_pending(
    rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    rdp.status = Rdp.PushStatus.SUCCESS
    mocker.patch.object(workflow, "lock_rdp_for_update", return_value=rdp)

    result = workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)

    assert result["evaluated"] is False
    assert result["outcome"] == Rdp.PushStatus.SUCCESS


def test_evaluate_rdp_for_push_waits_for_operations(
    rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(workflow, "has_incomplete_rdp_operations", return_value=True)

    result = workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)

    assert result["evaluated"] is False
    assert result["outcome"] == Rdp.PushStatus.PENDING


def test_evaluate_rdp_for_push_without_biometric_operation(
    rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(workflow, "has_incomplete_rdp_operations", return_value=False)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=None)
    append_log = mocker.patch.object(workflow, "append_rdp_log")
    schedule = mocker.patch.object(workflow, "_schedule_push_preparation")

    result = workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)

    assert result["evaluated"] is True
    assert result["outcome"] == Rdp.PushStatus.PUSH_PENDING
    assert "push_attempt_id" in result
    assert append_log.call_args.kwargs["entry_type"] == RdpLogEntryType.PUSH_TO_HOPE
    schedule.assert_called_once()


def test_evaluate_rdp_for_push_requires_individuals(
    rdp: Rdp,
    successful_biometric_operation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(workflow, "has_incomplete_rdp_operations", return_value=False)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=successful_biometric_operation)
    mocker.patch.object(workflow, "biometric_findings_count", return_value=1)
    individuals = mocker.patch.object(workflow, "qs_individuals_for_rdp")
    individuals.return_value.count.return_value = 0

    with pytest.raises(RdpWorkflowError):
        workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)


@pytest.mark.parametrize(
    ("exceeded", "status", "entry_type", "scheduled"),
    [
        (True, Rdp.PushStatus.REVIEW_PENDING, RdpLogEntryType.REVIEW_REQUIRED, False),
        (False, Rdp.PushStatus.PUSH_PENDING, RdpLogEntryType.PUSH_TO_HOPE, True),
    ],
)
def test_evaluate_rdp_for_push_with_biometric_threshold(
    rdp: Rdp,
    successful_biometric_operation,
    mocker: MockerFixture,
    exceeded: bool,
    status: Rdp.PushStatus,
    entry_type: RdpLogEntryType,
    scheduled: bool,
) -> None:
    successful_biometric_operation.config = {
        "threshold_type": "count",
        "threshold_value": "1",
    }
    mocker.patch.object(workflow, "lock_rdp_for_update", return_value=rdp)
    mocker.patch.object(workflow, "has_incomplete_rdp_operations", return_value=False)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=successful_biometric_operation)
    mocker.patch.object(workflow, "biometric_findings_count", return_value=2)
    individuals = mocker.patch.object(workflow, "qs_individuals_for_rdp")
    individuals.return_value.count.return_value = 10
    threshold = mocker.patch.object(workflow, "threshold_exceeded", return_value=exceeded)
    append_log = mocker.patch.object(workflow, "append_rdp_log")
    schedule = mocker.patch.object(workflow, "_schedule_push_preparation")

    result = workflow.evaluate_rdp_for_push(rdp_id=rdp.pk)

    assert result["evaluated"] is True
    assert result["outcome"] == status
    assert result["findings_count"] == 2
    assert result["individuals_count"] == 10
    assert result["findings_rate"] == "20.00"
    assert result["threshold_exceeded"] is exceeded

    threshold.assert_called_once_with(
        findings_count=2,
        total_count=10,
        threshold_type=ThresholdType.COUNT,
        threshold_value=Decimal(1),
    )
    assert append_log.call_args.kwargs["entry_type"] == entry_type
    assert schedule.called is scheduled


def test_evaluate_rdp_for_push_core(mocker: MockerFixture) -> None:
    job = mocker.MagicMock(config={"rdp_id": 12})
    evaluate = mocker.patch.object(
        workflow,
        "evaluate_rdp_for_push",
        return_value={"evaluated": True, "outcome": Rdp.PushStatus.PUSH_PENDING},
    )

    assert workflow.evaluate_rdp_for_push_core(job) == {
        "rdp_id": 12,
        "evaluated": True,
        "outcome": Rdp.PushStatus.PUSH_PENDING,
    }
    evaluate.assert_called_once_with(rdp_id=12)


def test_schedule_rdp_push_evaluation(
    rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock()
    create = mocker.patch.object(workflow.AsyncJob.objects, "create", return_value=job)
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    assert workflow.schedule_rdp_push_evaluation(rdp=rdp) is job

    assert create.call_args.kwargs["config"] == {"rdp_id": rdp.pk}
    assert create.call_args.kwargs["repeatable"] is True
    on_commit.assert_called_once_with(job.queue, robust=True)


@pytest.mark.parametrize(
    ("method", "status", "policy_method", "decision"),
    [
        ("claim_review_rdp_push", Rdp.PushStatus.REVIEW_PENDING, "review_push_check", "PUSH"),
        ("retry_rdp_push", Rdp.PushStatus.FAILURE, "retry_push_check", "RETRY"),
    ],
)
@pytest.mark.parametrize("allowed", [True, False])
def test_claim_push(
    rdp: Rdp,
    user,
    mocker: MockerFixture,
    method: str,
    status: Rdp.PushStatus,
    policy_method: str,
    decision: str,
    allowed: bool,
) -> None:
    rdp.status = status
    rdp.save(update_fields=["status"])
    mocker.patch.object(workflow, "lock_rdp_for_update", return_value=rdp)
    policy = mocker.MagicMock()
    getattr(policy, policy_method).return_value = ActionCheck(allowed, None if allowed else "blocked")
    mocker.patch.object(workflow, "get_push_policy", return_value=policy)
    append_log = mocker.patch.object(workflow, "append_rdp_log")
    schedule = mocker.patch.object(workflow, "_schedule_push_preparation")

    check, returned = getattr(workflow, method)(rdp.pk, user_id=user.pk)

    assert check.allowed is allowed

    if not allowed:
        assert returned is None
        append_log.assert_not_called()
        schedule.assert_not_called()
        return

    assert returned is rdp
    assert append_log.call_args.kwargs["result"]["decision"] == decision
    assert append_log.call_args.kwargs["result"]["user_id"] == str(user.pk)
    schedule.assert_called_once_with(rdp=rdp, user_id=user.pk)


def test_push_existing_rdp_without_reset(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
            "rdi_id_to_reset": None,
        }
    )
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=push_pending_rdp)
    push_job = mocker.MagicMock()
    schedule = mocker.patch.object(workflow, "_schedule_push_data", return_value=push_job)
    hope_api = mocker.patch.object(workflow, "HopeApi")

    result = workflow.push_existing_rdp_core(job)

    assert result["workflow_outcome"] == RdpWorkflowOutcome.DATA_PUSH_SCHEDULED
    assert result["reset_result"] is None
    schedule.assert_called_once()
    hope_api.assert_not_called()


@pytest.mark.parametrize(
    ("reset_result", "expected_outcome"),
    [
        (RdiResetResult.ACCEPTED, RdpWorkflowOutcome.AWAITING_PUSH_READY_CALLBACK),
        (RdiResetResult.NOT_FOUND, RdpWorkflowOutcome.DATA_PUSH_SCHEDULED),
        (RdiResetResult.ALREADY_MERGED, RdpWorkflowOutcome.DATA_PUSH_SKIPPED),
    ],
)
def test_push_existing_rdp_reset_result(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
    reset_result: RdiResetResult,
    expected_outcome: RdpWorkflowOutcome,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
            "rdi_id_to_reset": "RID",
        }
    )
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=push_pending_rdp)
    api = mocker.patch.object(workflow, "HopeApi").return_value
    api.reset_rdi.return_value = reset_result
    mocker.patch.object(workflow, "_build_push_ready_callback_url", return_value="/callback")
    mocker.patch.object(workflow, "_build_push_ready_callback_token", return_value="TOKEN")
    schedule = mocker.patch.object(workflow, "_schedule_push_data", return_value=mocker.MagicMock())
    finish = mocker.patch.object(workflow, "_finish_already_merged_push")

    result = workflow.push_existing_rdp_core(job)

    assert result["reset_result"] == reset_result.value
    assert result["workflow_outcome"] == expected_outcome
    assert schedule.called is (reset_result == RdiResetResult.NOT_FOUND)
    assert finish.called is (reset_result == RdiResetResult.ALREADY_MERGED)


def test_push_existing_rdp_merge_in_progress(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
            "rdi_id_to_reset": "RID",
        }
    )
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=push_pending_rdp)
    api = mocker.patch.object(workflow, "HopeApi").return_value
    api.reset_rdi.return_value = RdiResetResult.MERGE_IN_PROGRESS
    fail = mocker.patch.object(workflow, "_fail_pending_push")

    with pytest.raises(RdpWorkflowError, match="merge"):
        workflow.push_existing_rdp_core(job)

    fail.assert_called_once()


def test_push_existing_rdp_unconfirmed_reset(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
            "rdi_id_to_reset": "RID",
        }
    )
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=push_pending_rdp)
    api = mocker.patch.object(workflow, "HopeApi").return_value
    api.reset_rdi.side_effect = HopeRdiResetUnconfirmedError("unconfirmed")
    fail = mocker.patch.object(workflow, "_fail_pending_push")

    result = workflow.push_existing_rdp_core(job)

    assert result["workflow_outcome"] == RdpWorkflowOutcome.AWAITING_PUSH_READY_CALLBACK
    fail.assert_not_called()


def test_push_existing_rdp_wraps_error(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
            "rdi_id_to_reset": "RID",
        }
    )
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=push_pending_rdp)
    api = mocker.patch.object(workflow, "HopeApi").return_value
    api.reset_rdi.side_effect = RuntimeError("failed")
    fail = mocker.patch.object(workflow, "_fail_pending_push")

    with pytest.raises(RdpWorkflowError, match="failed"):
        workflow.push_existing_rdp_core(job)

    fail.assert_called_once()


def test_push_existing_rdp_rejects_stale_attempt(mocker: MockerFixture) -> None:
    push_attempt_id = uuid4()
    job = mocker.MagicMock(
        config={
            "rdp_id": 1,
            "push_attempt_id": str(push_attempt_id),
            "rdi_id_to_reset": None,
        }
    )
    mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=None)
    fail = mocker.patch.object(workflow, "_fail_pending_push")

    with pytest.raises(RdpWorkflowError, match="no longer current"):
        workflow.push_existing_rdp_core(job)

    fail.assert_called_once()


@pytest.mark.parametrize("scheduled", [True, False])
def test_handle_push_ready_callback(
    mocker: MockerFixture,
    scheduled: bool,
) -> None:
    job = mocker.MagicMock() if scheduled else None
    schedule = mocker.patch.object(workflow, "_schedule_push_data", return_value=job)
    push_attempt_id = uuid4()

    assert workflow.handle_push_ready_callback(rdp_id=1, push_attempt_id=push_attempt_id) is scheduled
    schedule.assert_called_once_with(rdp_id=1, push_attempt_id=push_attempt_id)


def test_handle_push_ready_callback_fails_attempt_on_error(
    mocker: MockerFixture,
) -> None:
    push_attempt_id = uuid4()
    mocker.patch.object(workflow, "_schedule_push_data", side_effect=RuntimeError("failed"))
    fail = mocker.patch.object(workflow, "_fail_pending_push")

    with pytest.raises(RuntimeError, match="failed"):
        workflow.handle_push_ready_callback(rdp_id=1, push_attempt_id=push_attempt_id)

    fail.assert_called_once_with(rdp_id=1, push_attempt_id=push_attempt_id, hope_rdi_id=None)


@pytest.mark.parametrize("master_detail", [True, False])
def test_push_data_steps(
    push_config,
    mocker: MockerFixture,
    master_detail: bool,
) -> None:
    config = push_config | {"master_detail": master_detail, "pks": [1, 2]}
    processor = mocker.MagicMock()
    individuals = mocker.patch.object(workflow, "qs_individuals_for_push", return_value="individuals")
    households = mocker.patch.object(workflow, "qs_households", return_value="households")
    people = mocker.patch.object(workflow, "qs_individuals_by_pks", return_value="people")

    steps = list(workflow._push_data_steps(processor, config))
    for step in steps:
        step()

    if master_detail:
        individuals.assert_called_once_with([1, 2])
        households.assert_called_once_with(pks=[1, 2])
        people.assert_not_called()
        assert processor.run_with.call_count == 2
    else:
        people.assert_called_once_with([1, 2])
        individuals.assert_not_called()
        households.assert_not_called()
        processor.run_with.assert_called_once()

    processor.rdi_complete.assert_called_once_with()


@pytest.mark.parametrize("has_errors", [True, False])
def test_raise_push_errors(
    mocker: MockerFixture,
    has_errors: bool,
) -> None:
    processor = mocker.MagicMock(has_errors=has_errors, total={"errors": ["failed"]})

    if has_errors:
        with pytest.raises(RdpWorkflowError):
            workflow._raise_push_errors(processor)
    else:
        workflow._raise_push_errors(processor)


@pytest.mark.parametrize("with_operation", [True, False])
def test_finish_successful_push(
    push_pending_rdp: Rdp,
    biometric_operation,
    mocker: MockerFixture,
    with_operation: bool,
) -> None:
    operation = biometric_operation if with_operation else None
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=operation)
    removed = mocker.patch.object(workflow, "set_rdp_beneficiaries_removed")
    finish = mocker.patch.object(push_pending_rdp, "finish_push_attempt")
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    workflow._finish_successful_push(rdp=push_pending_rdp, hope_rdi_id="RID")

    removed.assert_called_once_with(rdp=push_pending_rdp, removed=True)
    finish.assert_called_once_with(status=Rdp.PushStatus.SUCCESS, hope_rdi_id="RID")

    callback = on_commit.call_args.args[0]
    assert callback.keywords["operation_id"] == (operation.id if operation else None)


@pytest.mark.parametrize("active", [True, False])
def test_finish_already_merged_push(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
    active: bool,
) -> None:
    mocker.patch.object(
        workflow,
        "lock_rdp_push_attempt",
        return_value=push_pending_rdp if active else None,
    )
    finish = mocker.patch.object(workflow, "_finish_successful_push")
    signal = mocker.patch.object(workflow.rdp_push_status_changed_signal, "send_robust")

    workflow._finish_already_merged_push(
        rdp_id=push_pending_rdp.pk,
        push_attempt_id=push_pending_rdp.push_attempt_id,
        hope_rdi_id="RID",
    )

    assert finish.called is active
    assert signal.called is active


@pytest.mark.parametrize(
    ("owner_email", "expected_email"),
    [
        ("owner@example.com", "owner@example.com"),
        ("", "fallback@example.com"),
    ],
)
def test_push_rdp_data_core(
    push_pending_rdp: Rdp,
    push_config,
    mocker: MockerFixture,
    owner_email: str,
    expected_email: str,
) -> None:
    push_pending_rdp.pushed_by.email = "fallback@example.com"
    push_pending_rdp.pushed_by.save(update_fields=["email"])
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
        },
        owner=mocker.MagicMock(email=owner_email),
    )

    mocker.patch.object(workflow, "claim_rdp_data_push", return_value=push_pending_rdp)
    config = mocker.patch.object(workflow, "_workflow_config_for_rdp", return_value=push_config)
    processor_cls = mocker.patch.object(workflow, "PushProcessor")
    processor = processor_cls.return_value
    processor.hope_rdi_id = "NEW"
    processor.total = {"errors": [], "people": 2}

    mocker.patch.object(
        workflow,
        "lock_rdp_push_attempt",
        side_effect=[push_pending_rdp, push_pending_rdp],
    )
    step = mocker.Mock()
    mocker.patch.object(workflow, "_push_data_steps", return_value=[step])
    raise_errors = mocker.patch.object(workflow, "_raise_push_errors")
    finish = mocker.patch.object(workflow, "_finish_successful_push")
    completed = mocker.patch.object(workflow.rdi_push_completed_signal, "send_robust")
    status_changed = mocker.patch.object(workflow.rdp_push_status_changed_signal, "send_robust")

    assert workflow.push_rdp_data_core(job) == processor.total

    config.assert_called_once_with(rdp=push_pending_rdp, imported_by_email=expected_email)
    processor.preflight.assert_called_once_with()
    processor.rdi_create.assert_called_once_with()
    step.assert_called_once_with()
    assert raise_errors.call_count == 3
    finish.assert_called_once_with(rdp=push_pending_rdp, hope_rdi_id="NEW")
    assert completed.call_args.kwargs["pushed_count"] == 2
    status_changed.assert_called_once()

    push_pending_rdp.refresh_from_db()
    assert push_pending_rdp.hope_rdi_id == "NEW"


def test_push_rdp_data_core_skips_stale_attempt(
    push_pending_rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
        }
    )
    mocker.patch.object(workflow, "claim_rdp_data_push", return_value=None)
    processor = mocker.patch.object(workflow, "PushProcessor")

    assert workflow.push_rdp_data_core(job) == {
        "rdp_id": push_pending_rdp.pk,
        "workflow_outcome": RdpWorkflowOutcome.DATA_PUSH_SKIPPED,
    }
    processor.assert_not_called()


@pytest.mark.parametrize(
    ("case", "exception", "match"),
    [
        ("missing_rdi", AssertionError, "hope_rdi_id"),
        ("changed_after_create", RdpWorkflowError, "creating the new RDI"),
        ("changed_before_completion", RdpWorkflowError, "before completion"),
        ("rdi_mismatch", RuntimeError, "hope_rdi_id changed"),
    ],
)
def test_push_rdp_data_core_guards_state(
    push_pending_rdp: Rdp,
    push_config,
    mocker: MockerFixture,
    case: str,
    exception: type[Exception],
    match: str,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": push_pending_rdp.pk,
            "push_attempt_id": str(push_pending_rdp.push_attempt_id),
        },
        owner=mocker.MagicMock(email="owner@example.com"),
    )
    mocker.patch.object(workflow, "claim_rdp_data_push", return_value=push_pending_rdp)
    mocker.patch.object(workflow, "_workflow_config_for_rdp", return_value=push_config)
    processor = mocker.patch.object(workflow, "PushProcessor").return_value
    processor.total = {"errors": []}
    processor.hope_rdi_id = None if case == "missing_rdi" else "NEW"
    mocker.patch.object(workflow, "_raise_push_errors")
    mocker.patch.object(workflow, "_push_data_steps", return_value=[])

    if case == "changed_after_create":
        mocker.patch.object(workflow, "lock_rdp_push_attempt", return_value=None)
    elif case == "changed_before_completion":
        mocker.patch.object(
            workflow,
            "lock_rdp_push_attempt",
            side_effect=[push_pending_rdp, None],
        )
    elif case == "rdi_mismatch":
        changed = mocker.MagicMock(hope_rdi_id="OTHER")
        mocker.patch.object(
            workflow,
            "lock_rdp_push_attempt",
            side_effect=[push_pending_rdp, changed],
        )

    fail = mocker.patch.object(workflow, "_fail_pending_push")

    with pytest.raises(exception, match=match):
        workflow.push_rdp_data_core(job)

    fail.assert_called_once()
