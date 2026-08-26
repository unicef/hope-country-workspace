from uuid import uuid4

import pytest
from pytest_mock import MockerFixture
from django.db import IntegrityError

from country_workspace.contrib.dedup_engine import REJECTABLE_DEDUPLICATION_SET_STATES
from country_workspace.exceptions import RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.lifecycle import cancel_existing_rdp_core, create_rdp_core, reset_rdp
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


@pytest.mark.parametrize(
    "case",
    [
        (False, False, False),
        (True, False, False),
        (True, True, True),
    ],
    ids=["without_set", "non_rejectable", "rejectable"],
)
def test_cancel_existing_rdp(cancel_job: AsyncJob, rdp: Rdp, mocker: MockerFixture, case) -> None:
    has_set, rejectable, expected_rejected = case
    rdp.deduplication_set_id = uuid4() if has_set else None

    policy = mocker.MagicMock()
    policy.deduplication_set_state = next(iter(REJECTABLE_DEDUPLICATION_SET_STATES)) if rejectable else "OTHER"

    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    mocker.patch(f"{MOD}.require_policy_check")
    reject = mocker.patch(f"{MOD}.reject_deduplication_set")
    cancelled = mocker.patch.object(rdp, "mark_cancelled")

    result = cancel_existing_rdp_core(cancel_job)

    assert result == {
        "rdp_id": rdp.pk,
        "deduplication_set_rejected": expected_rejected,
    }
    assert reject.called is expected_rejected
    cancelled.assert_called_once_with()


def test_cancel_existing_rdp_remote_error(cancel_job: AsyncJob, rdp: Rdp, mocker: MockerFixture) -> None:
    rdp.deduplication_set_id = uuid4()
    policy = mocker.MagicMock(
        deduplication_set_state=next(iter(REJECTABLE_DEDUPLICATION_SET_STATES)),
    )

    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    mocker.patch(f"{MOD}.require_policy_check")
    mocker.patch(f"{MOD}.reject_deduplication_set", side_effect=RemoteUnavailableError("boom"))
    cancelled = mocker.patch.object(rdp, "mark_cancelled")

    with pytest.raises(RdpWorkflowError, match="boom"):
        cancel_existing_rdp_core(cancel_job)

    cancelled.assert_not_called()
