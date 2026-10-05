import pytest
from django.db import IntegrityError
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.models import Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp import lifecycle
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("errors", [[], ["invalid"]], ids=["valid", "invalid"])
def test_validate_rdp_creation(program, mocker: MockerFixture, errors: list[str]) -> None:
    preflight = mocker.patch.object(lifecycle, "preflight_errors", return_value=errors)
    config = {"pks": [1], "master_detail": False}

    if errors:
        with pytest.raises(RdpWorkflowError) as exc:
            lifecycle._validate_rdp_creation(program=program, config=config)

        assert exc.value.args[0]["errors"] == errors
    else:
        lifecycle._validate_rdp_creation(program=program, config=config)

    preflight.assert_called_once_with(pks=[1], master_detail=False, exclude_rdp_ids=())


def test_validate_rdp_creation_requires_beneficiary_group(program) -> None:
    program.beneficiary_group = None

    with pytest.raises(RdpWorkflowError):
        lifecycle._validate_rdp_creation(
            program=program,
            config={"pks": [1], "master_detail": False},
        )


def test_create_rdp_core(rdp: Rdp, mocker: MockerFixture) -> None:
    job = mocker.MagicMock(
        id=10,
        program=rdp.program,
        config={"program_id": rdp.program_id},
    )
    mocker.patch.object(lifecycle, "_validate_rdp_creation")
    created = mocker.MagicMock(id=123)
    mocker.patch.object(lifecycle, "create_rdp", return_value=created)
    update = mocker.patch.object(lifecycle.AsyncJob.objects, "filter")
    schedule = mocker.patch.object(lifecycle, "_schedule_rdp_processing")

    assert lifecycle.create_rdp_core(job) == {"rdp_id": 123}

    update.return_value.update.assert_called_once_with(rdp=created)
    schedule.assert_called_once_with(rdp=created)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("uniq_non_terminal_rdp_per_program", "unfinished"),
        ("other constraint", "create record"),
    ],
)
def test_create_rdp_core_converts_integrity_error(
    rdp: Rdp,
    mocker: MockerFixture,
    message: str,
    expected: str,
) -> None:
    job = mocker.MagicMock(program=rdp.program, config={"program_id": rdp.program_id})
    mocker.patch.object(lifecycle, "_validate_rdp_creation")
    mocker.patch.object(lifecycle, "create_rdp", side_effect=IntegrityError(message))

    with pytest.raises(RdpWorkflowError, match=expected):
        lifecycle.create_rdp_core(job)


@pytest.mark.parametrize("allowed", [False, True])
def test_reset_rdp(
    successful_rdp: Rdp,
    mocker: MockerFixture,
    allowed: bool,
) -> None:
    mocker.patch.object(lifecycle, "lock_rdp_for_update", return_value=successful_rdp)
    policy = mocker.patch.object(lifecycle, "get_rdp_policy").return_value
    policy.reset_check.return_value = check = ActionCheck(allowed, "blocked" if not allowed else None)
    removed = mocker.patch.object(lifecycle, "set_rdp_beneficiaries_removed")
    cancel = mocker.patch.object(successful_rdp, "mark_cancelled")

    assert lifecycle.reset_rdp(rdp_id=successful_rdp.pk) == (ActionCheck(True) if allowed else check)

    assert removed.called is allowed
    assert cancel.called is allowed


@pytest.mark.parametrize("with_operation", [True, False])
def test_schedule_rdp_processing(
    rdp: Rdp,
    mocker: MockerFixture,
    with_operation: bool,
) -> None:
    from testutils.factories import BiometricRdpOperationFactory

    if with_operation:
        BiometricRdpOperationFactory(rdp=rdp)

    operations = mocker.patch.object(lifecycle, "schedule_rdp_operations")
    push = mocker.patch.object(lifecycle, "schedule_rdp_push_evaluation")

    lifecycle._schedule_rdp_processing(rdp=rdp)

    assert operations.called is with_operation
    assert push.called is not with_operation


def test_biometric_rejection_check_without_operation(rdp: Rdp, mocker: MockerFixture) -> None:
    mocker.patch.object(lifecycle, "biometric_operation_for_rdp", return_value=None)
    retrieve = mocker.patch.object(lifecycle, "retrieve_deduplication_set_state")

    check, set_id = lifecycle._biometric_rejection_check(rdp)

    assert check.allowed is True
    assert set_id is None
    retrieve.assert_not_called()


@pytest.mark.parametrize(
    ("state", "allowed", "reject"),
    [
        (DeduplicationSetState.DEDUPLICATED, True, True),
        (DeduplicationSetState.REJECTED, True, False),
        (None, True, False),
        (DeduplicationSetState.ENCODING_IN_PROGRESS, False, False),
    ],
)
def test_biometric_rejection_check(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    state: DeduplicationSetState | None,
    allowed: bool,
    reject: bool,
) -> None:
    mocker.patch.object(lifecycle, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(lifecycle, "retrieve_deduplication_set_state", return_value=state)

    check, set_id = lifecycle._biometric_rejection_check(rdp)

    assert check.allowed is allowed
    assert (set_id == str(biometric_operation.id)) is reject


def test_cancel_rdp_rejects_initial_policy_check(rdp: Rdp, mocker: MockerFixture) -> None:
    policy = mocker.patch.object(lifecycle, "get_rdp_policy").return_value
    policy.cancel_check.return_value = check = ActionCheck(False, "blocked")
    biometric = mocker.patch.object(lifecycle, "_biometric_rejection_check")

    assert lifecycle.cancel_rdp(rdp.pk, user_id=1) == (check, False)
    biometric.assert_not_called()


def test_cancel_rdp_rejects_biometric_state(rdp: Rdp, mocker: MockerFixture) -> None:
    policy = mocker.patch.object(lifecycle, "get_rdp_policy").return_value
    policy.cancel_check.return_value = ActionCheck(True)
    rejection = ActionCheck(False, "blocked")
    mocker.patch.object(lifecycle, "_biometric_rejection_check", return_value=(rejection, None))
    lock = mocker.patch.object(lifecycle, "lock_rdp_for_update")

    assert lifecycle.cancel_rdp(rdp.pk, user_id=1) == (rejection, False)
    lock.assert_not_called()


def test_cancel_rdp_rechecks_policy_after_lock(rdp: Rdp, mocker: MockerFixture) -> None:
    first = mocker.MagicMock()
    first.cancel_check.return_value = ActionCheck(True)
    second = mocker.MagicMock()
    second.cancel_check.return_value = check = ActionCheck(False, "changed")
    mocker.patch.object(lifecycle, "get_rdp_policy", side_effect=[first, second])
    mocker.patch.object(lifecycle, "_biometric_rejection_check", return_value=(ActionCheck(True), None))
    mocker.patch.object(lifecycle, "lock_rdp_for_update", return_value=rdp)

    assert lifecycle.cancel_rdp(rdp.pk, user_id=1) == (check, False)


@pytest.mark.parametrize(
    ("status", "rejection_set_id", "logged"),
    [
        (Rdp.PushStatus.PENDING, None, False),
        (Rdp.PushStatus.REVIEW_PENDING, None, True),
        (Rdp.PushStatus.REVIEW_PENDING, "SET", True),
    ],
)
def test_cancel_rdp(
    rdp: Rdp,
    mocker: MockerFixture,
    status: Rdp.PushStatus,
    rejection_set_id: str | None,
    logged: bool,
) -> None:
    rdp.status = status
    rdp.save(update_fields=["status"])

    policy = mocker.patch.object(lifecycle, "get_rdp_policy").return_value
    policy.cancel_check.return_value = ActionCheck(True)
    mocker.patch.object(
        lifecycle,
        "_biometric_rejection_check",
        return_value=(ActionCheck(True), rejection_set_id),
    )
    mocker.patch.object(lifecycle, "lock_rdp_for_update", return_value=rdp)
    cancel = mocker.patch.object(rdp, "mark_cancelled")
    append = mocker.patch.object(lifecycle, "append_rdp_log")
    reject = mocker.patch.object(lifecycle, "schedule_cancelled_rdp_set_rejection")

    check, scheduled = lifecycle.cancel_rdp(rdp.pk, user_id=7)

    assert check.allowed is True
    assert scheduled is (rejection_set_id is not None)
    cancel.assert_called_once_with()
    assert append.called is logged
    assert reject.called is (rejection_set_id is not None)

    if logged:
        assert append.call_args.kwargs["entry_type"] == RdpLogEntryType.REVIEW_DECISION
        result = append.call_args.kwargs["result"]
        assert result["decision"] == "CANCEL"
        assert result["deduplication_set_rejection"] == ("scheduled" if rejection_set_id else "not_required")


@pytest.mark.parametrize(
    ("status", "operation_status", "state", "allowed"),
    [
        (Rdp.PushStatus.PENDING, RdpOperation.Status.SUCCESS, DeduplicationSetState.DEDUPLICATED, False),
        (Rdp.PushStatus.REVIEW_PENDING, None, DeduplicationSetState.DEDUPLICATED, False),
        (Rdp.PushStatus.REVIEW_PENDING, RdpOperation.Status.FAILURE, DeduplicationSetState.DEDUPLICATED, False),
        (Rdp.PushStatus.REVIEW_PENDING, RdpOperation.Status.SUCCESS, DeduplicationSetState.READY, False),
        (Rdp.PushStatus.REVIEW_PENDING, RdpOperation.Status.SUCCESS, DeduplicationSetState.DEDUPLICATED, True),
    ],
)
def test_clean_rdp_check(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    status: Rdp.PushStatus,
    operation_status: RdpOperation.Status | None,
    state: DeduplicationSetState,
    allowed: bool,
) -> None:
    rdp.status = status
    if operation_status is not None:
        biometric_operation.status = operation_status

    operation = biometric_operation if operation_status is not None else None
    mocker.patch.object(lifecycle, "biometric_operation_for_rdp", return_value=operation)
    retrieve = mocker.patch.object(lifecycle, "retrieve_deduplication_set_state", return_value=state)

    check, result = lifecycle._clean_rdp_check(rdp)

    assert check.allowed is allowed
    assert (result is biometric_operation) is allowed

    if status != Rdp.PushStatus.REVIEW_PENDING or operation_status != RdpOperation.Status.SUCCESS:
        retrieve.assert_not_called()


def test_clean_rdp_operation_configs(review_pending_rdp: Rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory

    BiometricRdpOperationFactory(
        rdp=review_pending_rdp,
        config={"threshold_type": "rate", "threshold_value": "25", "other": "value"},
    )

    [config] = lifecycle._clean_rdp_operation_configs(review_pending_rdp)

    assert config["operation_type"] == RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    assert config["config"] == {
        "threshold_type": "count",
        "threshold_value": "0",
        "other": "value",
    }


def test_create_clean_rdp_rejects_failed_check(review_pending_rdp: Rdp, mocker: MockerFixture) -> None:
    check = ActionCheck(False, "blocked")
    mocker.patch.object(lifecycle, "_clean_rdp_check", return_value=(check, None))

    assert lifecycle.create_clean_rdp(review_pending_rdp.pk, user_id=1) == (check, None)


def test_create_clean_rdp_rejects_empty_selection(
    review_pending_rdp: Rdp,
    successful_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(
        lifecycle,
        "_clean_rdp_check",
        return_value=(ActionCheck(True), successful_biometric_operation),
    )
    mocker.patch.object(lifecycle, "biometric_clean_rdp_selection", return_value=(False, []))

    check, clean_rdp = lifecycle.create_clean_rdp(review_pending_rdp.pk, user_id=1)

    assert check.allowed is False
    assert clean_rdp is None


@pytest.mark.parametrize("changed", ["status", "selection"])
def test_create_clean_rdp_rechecks_state_after_lock(
    review_pending_rdp: Rdp,
    successful_biometric_operation: RdpOperation,
    mocker: MockerFixture,
    changed: str,
) -> None:
    mocker.patch.object(
        lifecycle,
        "_clean_rdp_check",
        return_value=(ActionCheck(True), successful_biometric_operation),
    )
    selection = mocker.patch.object(lifecycle, "biometric_clean_rdp_selection", return_value=(False, [1]))
    mocker.patch.object(lifecycle, "lock_rdp_for_update", return_value=review_pending_rdp)

    if changed == "status":
        review_pending_rdp.status = Rdp.PushStatus.PENDING
    else:
        selection.side_effect = [(False, [1]), (False, [2])]

    check, clean_rdp = lifecycle.create_clean_rdp(review_pending_rdp.pk, user_id=1)

    assert check.allowed is False
    assert clean_rdp is None


def test_create_clean_rdp(
    review_pending_rdp: Rdp,
    successful_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(
        lifecycle,
        "_clean_rdp_check",
        return_value=(ActionCheck(True), successful_biometric_operation),
    )
    mocker.patch.object(lifecycle, "biometric_clean_rdp_selection", return_value=(False, [1, 2]))
    mocker.patch.object(lifecycle, "lock_rdp_for_update", return_value=review_pending_rdp)
    validate = mocker.patch.object(lifecycle, "_validate_rdp_creation")
    cancel = mocker.patch.object(review_pending_rdp, "mark_cancelled")
    clean_rdp = mocker.MagicMock(pk=123)
    create = mocker.patch.object(lifecycle, "create_rdp", return_value=clean_rdp)
    job = mocker.MagicMock(pk=456)
    reject = mocker.patch.object(lifecycle, "schedule_cancelled_rdp_set_rejection", return_value=job)
    append = mocker.patch.object(lifecycle, "append_rdp_log")

    check, result = lifecycle.create_clean_rdp(review_pending_rdp.pk, user_id=7)
    config = create.call_args.kwargs["config"]

    assert check.allowed is True
    assert result is clean_rdp
    cancel.assert_called_once_with()
    assert create.call_args.kwargs["config"]["pks"] == [1, 2]
    assert create.call_args.kwargs["config"]["pushed_by_id"] == 7
    reject.assert_called_once_with(
        rdp=review_pending_rdp,
        user_id=7,
        deduplication_set_id=str(successful_biometric_operation.id),
        clean_rdp_id=123,
    )
    assert append.call_args.kwargs["result"]["new_rdp_id"] == 123
    validate.assert_called_once_with(
        program=review_pending_rdp.program,
        config=config,
        exclude_rdp_ids=(review_pending_rdp.pk,),
    )


def test_create_clean_rdp_converts_integrity_error(
    review_pending_rdp: Rdp,
    successful_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(
        lifecycle,
        "_clean_rdp_check",
        return_value=(ActionCheck(True), successful_biometric_operation),
    )
    mocker.patch.object(lifecycle, "biometric_clean_rdp_selection", return_value=(False, [1]))
    mocker.patch.object(lifecycle, "lock_rdp_for_update", return_value=review_pending_rdp)
    mocker.patch.object(lifecycle, "_validate_rdp_creation")
    mocker.patch.object(review_pending_rdp, "mark_cancelled")
    mocker.patch.object(
        lifecycle,
        "create_rdp",
        side_effect=IntegrityError("uniq_non_terminal_rdp_per_program"),
    )

    with pytest.raises(RdpWorkflowError, match="unfinished"):
        lifecycle.create_clean_rdp(review_pending_rdp.pk, user_id=1)


def test_cancel_existing_rdp_core_requires_owner(mocker: MockerFixture) -> None:
    job = mocker.MagicMock(owner_id=None)

    with pytest.raises(RdpWorkflowError, match="owner"):
        lifecycle.cancel_existing_rdp_core(job)


def test_cancel_existing_rdp_core(mocker: MockerFixture) -> None:
    job = mocker.MagicMock(owner_id=7, config={"rdp_id": 12})
    cancel = mocker.patch.object(
        lifecycle,
        "cancel_rdp",
        return_value=(ActionCheck(True), True),
    )

    assert lifecycle.cancel_existing_rdp_core(job) == {
        "rdp_id": 12,
        "deduplication_set_rejection_scheduled": True,
    }
    cancel.assert_called_once_with(rdp_id=12, user_id=7)
