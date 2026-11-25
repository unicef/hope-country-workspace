from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Program, Rdp
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.lifecycle import cancellation
from country_workspace.rdp.policy import ActionCheck


pytestmark = pytest.mark.django_db


def test_cancel_rdp_rejects_initial_policy_check(rdp: Rdp, mocker: MockerFixture) -> None:
    policy = mocker.patch.object(cancellation, "get_rdp_policy").return_value
    policy.cancel_check.return_value = check = ActionCheck(False, "blocked")
    rejections = mocker.patch.object(cancellation, "check_cancellation_rejections")

    assert cancellation.cancel_rdp(rdp.pk, user_id=1) == (check, False)
    rejections.assert_not_called()


def test_cancel_rdp_rejects_deduplication_state(rdp: Rdp, mocker: MockerFixture) -> None:
    policy = mocker.patch.object(cancellation, "get_rdp_policy").return_value
    policy.cancel_check.return_value = ActionCheck(True)
    rejection = ActionCheck(False, "blocked")
    mocker.patch.object(cancellation, "check_cancellation_rejections", return_value=(rejection, ()))
    lock = mocker.patch.object(cancellation, "lock_rdp_for_update")

    assert cancellation.cancel_rdp(rdp.pk, user_id=1) == (rejection, False)
    lock.assert_not_called()


def test_cancel_rdp_rechecks_policy_after_lock(rdp: Rdp, mocker: MockerFixture) -> None:
    first = mocker.MagicMock()
    first.cancel_check.return_value = ActionCheck(True)
    second = mocker.MagicMock()
    second.cancel_check.return_value = check = ActionCheck(False, "changed")
    mocker.patch.object(cancellation, "get_rdp_policy", side_effect=[first, second])
    mocker.patch.object(cancellation, "check_cancellation_rejections", return_value=(ActionCheck(True), ()))
    mocker.patch.object(cancellation, "lock_rdp_for_update", return_value=rdp)

    assert cancellation.cancel_rdp(rdp.pk, user_id=1) == (check, False)


@pytest.mark.parametrize(
    ("status", "rejection_operation_ids", "logged"),
    [
        (Rdp.PushStatus.PENDING, (), False),
        (Rdp.PushStatus.REVIEW_PENDING, (), True),
        (Rdp.PushStatus.REVIEW_PENDING, (uuid4(),), True),
        (Rdp.PushStatus.REVIEW_PENDING, (uuid4(), uuid4()), True),
    ],
)
def test_cancel_rdp(
    rdp: Rdp,
    mocker: MockerFixture,
    status: Rdp.PushStatus,
    rejection_operation_ids: tuple,
    logged: bool,
) -> None:
    rdp.status = status
    rdp.save(update_fields=["status"])

    policy = mocker.patch.object(cancellation, "get_rdp_policy").return_value
    policy.cancel_check.return_value = ActionCheck(True)
    mocker.patch.object(
        cancellation,
        "check_cancellation_rejections",
        return_value=(ActionCheck(True), rejection_operation_ids),
    )
    mocker.patch.object(cancellation, "lock_rdp_for_update", return_value=rdp)
    cancel = mocker.patch.object(rdp, "mark_cancelled")
    append = mocker.patch.object(cancellation, "append_rdp_log")
    reject = mocker.patch.object(cancellation, "schedule_cancelled_rdp_set_rejection")

    check, scheduled = cancellation.cancel_rdp(rdp.pk, user_id=7)
    should_reject = bool(rejection_operation_ids)

    assert check.allowed is True
    assert scheduled is should_reject
    cancel.assert_called_once_with()
    assert append.called is logged
    assert reject.called is should_reject
    if should_reject:
        assert reject.call_args.kwargs["operation_ids"] == rejection_operation_ids

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
    rejection_check = mocker.patch.object(cancellation, "check_cancellation_rejections")
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
