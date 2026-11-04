import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.models import Program, Rdp, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.lifecycle import cancellation
from country_workspace.rdp.policy import ActionCheck


pytestmark = pytest.mark.django_db


def test_biometric_rejection_check_without_operation(rdp: Rdp, mocker: MockerFixture) -> None:
    mocker.patch.object(cancellation, "biometric_operation_for_rdp", return_value=None)
    retrieve = mocker.patch.object(cancellation, "retrieve_deduplication_set_state")

    check, set_id = cancellation._biometric_rejection_check(rdp)

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
    mocker.patch.object(cancellation, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(cancellation, "retrieve_deduplication_set_state", return_value=state)

    check, set_id = cancellation._biometric_rejection_check(rdp)

    assert check.allowed is allowed
    assert set_id == (str(biometric_operation.id) if reject else None)


def test_cancel_rdp_rejects_initial_policy_check(rdp: Rdp, mocker: MockerFixture) -> None:
    policy = mocker.patch.object(cancellation, "get_rdp_policy").return_value
    policy.cancel_check.return_value = check = ActionCheck(False, "blocked")
    biometric = mocker.patch.object(cancellation, "_biometric_rejection_check")

    assert cancellation.cancel_rdp(rdp.pk, user_id=1) == (check, False)
    biometric.assert_not_called()


def test_cancel_rdp_rejects_biometric_state(rdp: Rdp, mocker: MockerFixture) -> None:
    policy = mocker.patch.object(cancellation, "get_rdp_policy").return_value
    policy.cancel_check.return_value = ActionCheck(True)
    rejection = ActionCheck(False, "blocked")
    mocker.patch.object(cancellation, "_biometric_rejection_check", return_value=(rejection, None))
    lock = mocker.patch.object(cancellation, "lock_rdp_for_update")

    assert cancellation.cancel_rdp(rdp.pk, user_id=1) == (rejection, False)
    lock.assert_not_called()


def test_cancel_rdp_rechecks_policy_after_lock(rdp: Rdp, mocker: MockerFixture) -> None:
    first = mocker.MagicMock()
    first.cancel_check.return_value = ActionCheck(True)
    second = mocker.MagicMock()
    second.cancel_check.return_value = check = ActionCheck(False, "changed")
    mocker.patch.object(cancellation, "get_rdp_policy", side_effect=[first, second])
    mocker.patch.object(cancellation, "_biometric_rejection_check", return_value=(ActionCheck(True), None))
    mocker.patch.object(cancellation, "lock_rdp_for_update", return_value=rdp)

    assert cancellation.cancel_rdp(rdp.pk, user_id=1) == (check, False)


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

    policy = mocker.patch.object(cancellation, "get_rdp_policy").return_value
    policy.cancel_check.return_value = ActionCheck(True)
    mocker.patch.object(
        cancellation,
        "_biometric_rejection_check",
        return_value=(ActionCheck(True), rejection_set_id),
    )
    mocker.patch.object(cancellation, "lock_rdp_for_update", return_value=rdp)
    cancel = mocker.patch.object(rdp, "mark_cancelled")
    append = mocker.patch.object(cancellation, "append_rdp_log")
    reject = mocker.patch.object(cancellation, "schedule_cancelled_rdp_set_rejection")

    check, scheduled = cancellation.cancel_rdp(rdp.pk, user_id=7)
    should_reject = rejection_set_id is not None

    assert check.allowed is True
    assert scheduled is should_reject
    cancel.assert_called_once_with()
    assert append.called is logged
    assert reject.called is should_reject

    if logged:
        assert append.call_args.kwargs["entry_type"] == RdpLogEntryType.REVIEW_DECISION
        result = append.call_args.kwargs["result"]
        assert result["decision"] == "CANCEL"
        assert result["deduplication_set_rejection"] == ("scheduled" if should_reject else "not_required")


def test_cancel_rdp_during_program_cleanup(rdp: Rdp, mocker: MockerFixture) -> None:
    rdp.status = Rdp.PushStatus.FAILURE
    rdp.save(update_fields=["status"])
    Program.objects.filter(pk=rdp.program_id).update(cleanup_in_progress=True)

    policy = mocker.patch.object(cancellation, "get_rdp_policy").return_value
    policy.cancel_check.return_value = ActionCheck(True)
    rejection_check = mocker.patch.object(cancellation, "_biometric_rejection_check")
    reject = mocker.patch.object(cancellation, "schedule_cancelled_rdp_set_rejection")

    check, scheduled = cancellation.cancel_rdp(rdp.pk, user_id=7)

    assert check.allowed is True
    assert scheduled is False
    rejection_check.assert_not_called()
    reject.assert_not_called()
    rdp.refresh_from_db()
    assert rdp.status == Rdp.PushStatus.CANCELLED


def test_cancel_existing_rdp_core_requires_owner(mocker: MockerFixture) -> None:
    job = mocker.MagicMock(owner_id=None)

    with pytest.raises(RdpWorkflowError, match="owner"):
        cancellation.cancel_existing_rdp_core(job)


def test_cancel_existing_rdp_core(mocker: MockerFixture) -> None:
    job = mocker.MagicMock(owner_id=7, config={"rdp_id": 12})
    cancel = mocker.patch.object(
        cancellation,
        "cancel_rdp",
        return_value=(ActionCheck(True), True),
    )

    assert cancellation.cancel_existing_rdp_core(job) == {
        "rdp_id": 12,
        "deduplication_set_rejection_scheduled": True,
    }
    cancel.assert_called_once_with(rdp_id=12, user_id=7)
