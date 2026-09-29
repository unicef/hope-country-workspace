from uuid import uuid4

import pytest
from django.db import IntegrityError
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.lifecycle import (
    cancel_existing_rdp_core,
    claim_rdp_cancel,
    create_rdp_core,
    reject_cancelled_rdp_set_core,
    reset_rdp,
)
from country_workspace.rdp.policy import ActionCheck

MOD = "country_workspace.rdp.lifecycle"

pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp(user) -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(
        pushed_by=user,
        status=Rdp.PushStatus.PUSH_PENDING,
        hope_rdi_id=None,
        is_dedup_settings_locked=True,
    )


@pytest.fixture
def create_job(user) -> AsyncJob:
    from testutils.factories import AsyncJobFactory, CountryHouseholdFactory, CountryProgramFactory

    program = CountryProgramFactory(
        beneficiary_group__master_detail=True,
        biometric_deduplication_enabled=False,
    )
    household = CountryHouseholdFactory(batch__program=program)
    config = {
        "pks": [household.pk],
        "master_detail": True,
        "batch_name": "RDP",
        "country_office_id": program.country_office_id,
        "program_id": program.pk,
        "pushed_by_id": user.pk,
    }
    return AsyncJobFactory(program=program, owner=user, config=config)


@pytest.fixture
def cancel_job(rdp: Rdp) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(program=rdp.program, rdp=rdp, config={"rdp_id": rdp.pk})


@pytest.mark.parametrize("case", ["beneficiary_group", "preflight"], ids=["no_beneficiary_group", "preflight"])
def test_create_rdp_validation(create_job: AsyncJob, mocker: MockerFixture, case: str) -> None:
    if case == "beneficiary_group":
        create_job.program.beneficiary_group = None
    else:
        mocker.patch(f"{MOD}.preflight_errors", return_value=["invalid"])

    with pytest.raises(RdpWorkflowError) as exc_info:
        create_rdp_core(create_job)

    assert ("beneficiary_group" if case == "beneficiary_group" else "invalid") in str(exc_info.value)


@pytest.mark.parametrize("case", ["rejected", "unavailable"], ids=["dedup_rejected", "dedup_unavailable"])
def test_create_rdp_dedup_validation(create_job: AsyncJob, mocker: MockerFixture, case: str) -> None:
    create_job.program.biometric_deduplication_enabled = True
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    make_client = mocker.patch(f"{MOD}.make_dedup_client")

    if case == "rejected":
        make_client.return_value.__enter__.return_value.can_create_deduplication_set.return_value = False
    else:
        make_client.side_effect = RemoteUnavailableError("boom")

    with pytest.raises(RdpWorkflowError):
        create_rdp_core(create_job)


def test_create_rdp(create_job: AsyncJob, mocker: MockerFixture) -> None:
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    result = create_rdp_core(create_job)

    rdp = Rdp.objects.get(pk=result["rdp_id"])
    create_job.refresh_from_db()

    assert rdp.status == Rdp.PushStatus.PENDING
    assert rdp.name == create_job.config["batch_name"]
    assert list(rdp.households.values_list("pk", flat=True)) == create_job.config["pks"]
    assert create_job.rdp_id == rdp.pk


@pytest.mark.parametrize(
    "case",
    [
        ("boom", "can not create record"),
        ("uniq_non_terminal_rdp_per_program", "another RDP is unfinished"),
    ],
    ids=["generic", "unfinished_rdp"],
)
def test_create_rdp_integrity_error(create_job: AsyncJob, mocker: MockerFixture, case) -> None:
    error, message = case
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch(f"{MOD}.Rdp.objects.create", side_effect=IntegrityError(error))

    with pytest.raises(RdpWorkflowError) as exc_info:
        create_rdp_core(create_job)

    assert message in str(exc_info.value)


@pytest.mark.parametrize("allowed", [True, False], ids=["allowed", "denied"])
def test_reset_rdp(rdp: Rdp, mocker: MockerFixture, allowed: bool) -> None:
    policy = mocker.MagicMock()
    policy.reset_check.return_value = ActionCheck(allowed, None if allowed else "blocked")
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    removed = mocker.patch(f"{MOD}.set_rdp_beneficiaries_removed")
    cancelled = mocker.patch.object(rdp, "mark_cancelled")

    result = reset_rdp(rdp_id=rdp.pk)

    assert result.allowed is allowed
    assert removed.called is allowed
    assert cancelled.called is allowed


@pytest.fixture
def cancellable_rdp(user) -> Rdp:
    """Build an RDP that may be cancelled from review."""
    from testutils.factories import CountryProgramFactory, CountryRdpFactory

    program = CountryProgramFactory(biometric_deduplication_enabled=True)
    return CountryRdpFactory(
        program=program,
        pushed_by=user,
        status=Rdp.PushStatus.REVIEW_PENDING,
        hope_rdi_id=None,
        deduplication_set_id=uuid4(),
        deduplication_findings_count=2,
    )


@pytest.mark.parametrize(
    ("has_set", "state", "queued"),
    [
        (False, None, False),
        (True, DeduplicationSetState.REJECTED, False),
        (True, DeduplicationSetState.DEDUPLICATED, True),
    ],
    ids=["without_set", "already_rejected", "requires_rejection"],
)
def test_claim_rdp_cancel(
    cancellable_rdp: Rdp,
    mocker: MockerFixture,
    django_capture_on_commit_callbacks,
    has_set: bool,
    state: str | None,
    queued: bool,
) -> None:
    """Cancel immediately and enqueue exactly one separate rejection task when required."""
    rdp = cancellable_rdp
    if not has_set:
        rdp.deduplication_set_id = None
        rdp.save(update_fields=["deduplication_set_id"])
    remote_policy = mocker.Mock(deduplication_set_state=state)
    mocker.patch(f"{MOD}.get_deduplication_policy", return_value=remote_policy)
    reject = mocker.patch(f"{MOD}.reject_deduplication_set")
    queue = mocker.patch.object(AsyncJob, "queue")

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        check, rejection_queued = claim_rdp_cancel(rdp.pk, user_id=rdp.pushed_by_id)

    rdp.refresh_from_db()
    jobs = list(AsyncJob.objects.filter(rdp=rdp))
    assert check.allowed is True
    assert rejection_queued is queued
    assert rdp.status == Rdp.PushStatus.CANCELLED
    assert rdp.push_attempt_id is None
    assert rdp.operation_log[-1]["action"] == RdpLogEntryType.REVIEW_DECISION
    assert rdp.operation_log[-1]["result"]["deduplication_set_rejection"] == ("queued" if queued else "not_required")
    assert len(jobs) == int(queued)
    assert len(callbacks) == int(queued)
    if queued:
        job = jobs[0]
        assert job.config == {"rdp_id": rdp.pk, "deduplication_set_id": str(rdp.deduplication_set_id)}
        assert job.action == f"{MOD}.reject_cancelled_rdp_set_core"
        assert job.type == AsyncJob.JobType.TASK
        assert job.owner_id == rdp.pushed_by_id
        queue.assert_called_once_with()
    else:
        queue.assert_not_called()
    reject.assert_not_called()


def test_cancel_existing_rdp_core(cancellable_rdp: Rdp, mocker: MockerFixture) -> None:
    """Legacy cancellation task delegates to the current claim workflow."""
    from testutils.factories import AsyncJobFactory

    rdp = cancellable_rdp
    job = AsyncJobFactory(program=rdp.program, rdp=rdp, owner=rdp.pushed_by, config={"rdp_id": rdp.pk})
    claim = mocker.patch(f"{MOD}.claim_rdp_cancel", return_value=(ActionCheck(True), True))

    assert cancel_existing_rdp_core(job) == {"rdp_id": rdp.pk, "deduplication_set_rejection_queued": True}
    claim.assert_called_once_with(rdp_id=rdp.pk, user_id=rdp.pushed_by_id)


def test_cancel_existing_rdp_core_denied(cancellable_rdp: Rdp, mocker: MockerFixture) -> None:
    """Legacy cancellation task propagates a denied claim."""
    from testutils.factories import AsyncJobFactory

    rdp = cancellable_rdp
    job = AsyncJobFactory(program=rdp.program, rdp=rdp, owner=rdp.pushed_by, config={"rdp_id": rdp.pk})
    mocker.patch(f"{MOD}.claim_rdp_cancel", return_value=(ActionCheck(False, "blocked"), False))

    with pytest.raises(RdpWorkflowError, match="blocked"):
        cancel_existing_rdp_core(job)


def test_claim_rdp_cancel_twice(cancellable_rdp: Rdp, mocker: MockerFixture) -> None:
    """A repeated cancellation cannot schedule another rejection."""
    rdp = cancellable_rdp
    mocker.patch(
        f"{MOD}.get_deduplication_policy",
        return_value=mocker.Mock(
            deduplication_set_state=DeduplicationSetState.DEDUPLICATED,
        ),
    )
    queue = mocker.patch.object(AsyncJob, "queue")

    assert claim_rdp_cancel(rdp.pk, user_id=rdp.pushed_by_id) == (ActionCheck(True), True)
    check, queued = claim_rdp_cancel(rdp.pk, user_id=rdp.pushed_by_id)

    assert not check.allowed
    assert queued is False
    assert AsyncJob.objects.filter(rdp=rdp).count() == 1
    queue.assert_not_called()


@pytest.mark.parametrize("changed", ["status", "deduplication_set_id", "deduplication_findings_count", "locked"])
def test_claim_rdp_cancel_rechecks_locked_rdp(
    cancellable_rdp: Rdp,
    mocker: MockerFixture,
    changed: str,
) -> None:
    """Reject stale cancellation decisions without changing the persisted RDP."""
    rdp = cancellable_rdp
    mocker.patch(
        f"{MOD}.get_deduplication_policy",
        return_value=mocker.Mock(
            deduplication_set_state=DeduplicationSetState.DEDUPLICATED,
        ),
    )
    from country_workspace.rdp.repository import lock_rdp_for_update as original_lock

    def changed_lock(*, pk: int) -> Rdp:
        locked = original_lock(pk=pk)
        if changed == "status":
            locked.status = Rdp.PushStatus.CANCELLED
        elif changed == "locked":
            locked.is_dedup_settings_locked = True
        elif changed == "deduplication_set_id":
            locked.deduplication_set_id = uuid4()
        else:
            locked.deduplication_findings_count = 999
        return locked

    mocker.patch(f"{MOD}.lock_rdp_for_update", side_effect=changed_lock)
    create = mocker.patch(f"{MOD}.AsyncJob.objects.create")

    check, queued = claim_rdp_cancel(rdp.pk, user_id=rdp.pushed_by_id)

    rdp.refresh_from_db()
    assert not check.allowed
    assert queued is False
    assert rdp.status == Rdp.PushStatus.REVIEW_PENDING
    assert rdp.operation_log == []
    create.assert_not_called()


@pytest.mark.parametrize("error", [RemoteError("missing"), RemoteUnavailableError("offline")])
def test_claim_rdp_cancel_remote_failure(cancellable_rdp: Rdp, mocker: MockerFixture, error: Exception) -> None:
    """Do not cancel locally if the remote state cannot be verified."""
    rdp = cancellable_rdp
    mocker.patch(
        f"{MOD}.get_deduplication_policy",
        return_value=mocker.Mock(
            deduplication_set_state=DeduplicationSetState.DEDUPLICATED,
            cancel_check=mocker.Mock(side_effect=error),
        ),
    )

    with pytest.raises(type(error)):
        claim_rdp_cancel(rdp.pk, user_id=rdp.pushed_by_id)

    rdp.refresh_from_db()
    assert rdp.status == Rdp.PushStatus.REVIEW_PENDING
    assert not AsyncJob.objects.filter(rdp=rdp).exists()


@pytest.mark.parametrize(
    ("state", "reject_called"),
    [(DeduplicationSetState.DEDUPLICATED, True), (DeduplicationSetState.REJECTED, False)],
)
def test_reject_cancelled_rdp_set_core(
    cancellable_rdp: Rdp,
    mocker: MockerFixture,
    state: str,
    reject_called: bool,
) -> None:
    """Reject a pending set and treat a previously rejected set as completed."""
    from testutils.factories import AsyncJobFactory

    rdp = cancellable_rdp
    rdp.mark_cancelled()
    job = AsyncJobFactory(
        program=rdp.program,
        rdp=rdp,
        owner=rdp.pushed_by,
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(rdp.deduplication_set_id),
        },
    )
    mocker.patch(f"{MOD}.get_deduplication_policy", return_value=mocker.Mock(deduplication_set_state=state))
    reject = mocker.patch(f"{MOD}.reject_deduplication_set")

    assert reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}
    assert reject.called is reject_called
    if reject_called:
        reject.assert_called_once_with(
            group_reference_id=rdp.program.unicef_id,
            deduplication_set_id=str(rdp.deduplication_set_id),
        )


@pytest.mark.parametrize("stale", ["status", "set_id", "remote_state", "remote_error"])
def test_reject_cancelled_rdp_set_core_rejects_invalid_job(
    cancellable_rdp: Rdp,
    mocker: MockerFixture,
    stale: str,
) -> None:
    """Avoid rejecting an unrelated or no longer rejectable set."""
    from testutils.factories import AsyncJobFactory

    rdp = cancellable_rdp
    if stale != "status":
        rdp.mark_cancelled()
    set_id = str(uuid4()) if stale == "set_id" else str(rdp.deduplication_set_id)
    job = AsyncJobFactory(
        program=rdp.program,
        rdp=rdp,
        owner=rdp.pushed_by,
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": set_id,
        },
    )
    remote = mocker.Mock(deduplication_set_state=DeduplicationSetState.READY)
    if stale == "remote_error":
        type(remote).deduplication_set_state = mocker.PropertyMock(side_effect=RemoteUnavailableError("offline"))
    mocker.patch(f"{MOD}.get_deduplication_policy", return_value=remote)
    reject = mocker.patch(f"{MOD}.reject_deduplication_set")

    with pytest.raises(RdpWorkflowError):
        reject_cancelled_rdp_set_core(job)
    reject.assert_not_called()


def test_claim_rdp_cancel_denied_without_remote_lookup(cancellable_rdp: Rdp, mocker: MockerFixture) -> None:
    """A disallowed local state does not read the remote set or create a job."""
    rdp = cancellable_rdp
    rdp.status = Rdp.PushStatus.PUSH_PENDING
    rdp.push_attempt_id = uuid4()
    rdp.save(update_fields=["status", "push_attempt_id"])
    remote = mocker.Mock()
    remote.cancel_check.return_value = ActionCheck(False, "blocked")
    type(remote).deduplication_set_state = mocker.PropertyMock(side_effect=AssertionError("unexpected DE read"))
    mocker.patch(f"{MOD}.get_deduplication_policy", return_value=remote)
    create = mocker.patch(f"{MOD}.AsyncJob.objects.create")

    assert claim_rdp_cancel(rdp.pk, user_id=rdp.pushed_by_id) == (ActionCheck(False, "blocked"), False)
    create.assert_not_called()
