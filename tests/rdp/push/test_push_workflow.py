from uuid import UUID, uuid4

import pytest
from constance.test import override_config
from django.core import signing
from pytest_mock import MockerFixture
from strategy_field.utils import fqn

from country_workspace.contrib.hope.rdi import HopeRdiResetUnconfirmedError, RdiResetResult
from country_workspace.models import AsyncJob, Rdp
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.push.constants import PUSH_READY_CALLBACK_SALT
from country_workspace.rdp.push.workflow import (
    _build_push_ready_callback_url,
    _fail_pending_push,
    _push_data_steps,
    _schedule_push_data,
    _workflow_config_for_rdp,
    claim_rdp_push,
    handle_push_ready_callback,
    push_existing_rdp_core,
    push_rdp_data_core,
)
from country_workspace.rdp.types import RdpWorkflowOutcome

MOD = "country_workspace.rdp.push.workflow"

pytestmark = pytest.mark.django_db


@pytest.fixture
def push_attempt_id() -> UUID:
    return uuid4()


@pytest.fixture
def rdp(user) -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(
        pushed_by=user,
        status=Rdp.PushStatus.PENDING,
        hope_rdi_id=None,
        deduplication_set_id=None,
    )


@pytest.fixture
def preparation_job(mocker: MockerFixture, rdp: Rdp, push_attempt_id: UUID) -> AsyncJob:
    job = mocker.MagicMock(spec=AsyncJob)
    job.config = {
        "rdp_id": rdp.pk,
        "push_attempt_id": str(push_attempt_id),
        "rdi_id_to_reset": None,
    }
    return job


@pytest.fixture
def data_job(mocker: MockerFixture, rdp: Rdp, push_attempt_id: UUID) -> AsyncJob:
    job = mocker.MagicMock(spec=AsyncJob)
    job.pk = 11
    job.config = {
        "rdp_id": rdp.pk,
        "push_attempt_id": str(push_attempt_id),
    }
    job.owner.email = "owner@example.org"
    return job


@pytest.fixture
def processor(mocker: MockerFixture):
    processor = mocker.MagicMock()
    processor.has_errors = False
    processor.hope_rdi_id = "NEW-RDI"
    processor.total = {}
    return processor


@pytest.fixture
def run_on_commit(mocker: MockerFixture):
    return mocker.patch(f"{MOD}.transaction.on_commit", side_effect=lambda callback, **kwargs: callback())


@pytest.fixture
def push_data_setup(rdp: Rdp, data_job: AsyncJob, processor, mocker: MockerFixture):
    config = {
        "batch_name": rdp.name,
        "co_slug": rdp.program.country_office.slug,
        "imported_by_email": "owner@example.org",
        "master_detail": False,
        "pks": [10],
        "program_hope_id": rdp.program.hope_id,
        "rdp_id": rdp.pk,
    }
    mocker.patch(f"{MOD}.claim_rdp_data_push", return_value=rdp)
    build_config = mocker.patch(f"{MOD}._workflow_config_for_rdp", return_value=config)
    mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    mocker.patch(f"{MOD}._push_data_steps", return_value=[processor.rdi_complete])
    mocker.patch.object(rdp, "save")
    return rdp, data_job, processor, build_config


@override_config(APP_BASE_URL="https://cw.example.org/")
def test_build_push_ready_callback_url(push_attempt_id: UUID) -> None:
    url = _build_push_ready_callback_url(rdp_id=7, push_attempt_id=push_attempt_id)
    signed_token = url.rstrip("/").rsplit("/", 1)[-1]

    assert url.startswith("https://cw.example.org/")
    assert signing.loads(signed_token, salt=PUSH_READY_CALLBACK_SALT) == {
        "rdp_id": 7,
        "push_attempt_id": str(push_attempt_id),
    }


@pytest.mark.parametrize(
    "case",
    [
        (False, False),
        (False, True),
        (True, False),
        (True, True),
    ],
    ids=["disabled_without_set", "disabled_with_set", "enabled_without_set", "enabled_with_set"],
)
def test_workflow_config_for_rdp(rdp: Rdp, mocker: MockerFixture, case) -> None:
    biometric_enabled, has_deduplication_set = case
    rdp.program.biometric_deduplication_enabled = biometric_enabled
    rdp.deduplication_set_id = deduplication_set_id = uuid4() if has_deduplication_set else None
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [10, 20]))

    config = _workflow_config_for_rdp(rdp=rdp, imported_by_email="user@example.org")

    assert config == {
        "batch_name": rdp.name,
        "co_slug": rdp.program.country_office.slug,
        "imported_by_email": "user@example.org",
        "master_detail": True,
        "pks": [10, 20],
        "program_hope_id": rdp.program.hope_id,
        "rdp_id": rdp.pk,
        **({"country_workspace_id": str(deduplication_set_id)} if biometric_enabled and deduplication_set_id else {}),
    }


def test_workflow_config_uses_rdp_string_when_name_is_empty(rdp: Rdp, mocker: MockerFixture) -> None:
    rdp.name = ""
    mocker.patch(f"{MOD}.rdp_selection", return_value=(False, []))

    assert _workflow_config_for_rdp(rdp=rdp, imported_by_email="user@example.org")["batch_name"] == str(rdp)


def test_fail_pending_push_ignores_stale_attempt(rdp: Rdp, push_attempt_id: UUID, mocker: MockerFixture) -> None:
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=None)
    finish = mocker.patch.object(rdp, "finish_push_attempt")

    _fail_pending_push(rdp_id=rdp.pk, push_attempt_id=push_attempt_id, hope_rdi_id=None)

    finish.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        (None, None, "N/A"),
        ("N/A", "OLD-RDI", "OLD-RDI"),
        ("CURRENT-RDI", "OLD-RDI", "CURRENT-RDI"),
    ],
    ids=["no_rdi", "fallback_rdi", "current_rdi"],
)
def test_fail_pending_push(rdp: Rdp, push_attempt_id: UUID, mocker: MockerFixture, run_on_commit, case) -> None:
    current_rdi_id, fallback_rdi_id, expected_rdi_id = case
    rdp.hope_rdi_id = current_rdi_id

    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)
    finish = mocker.patch.object(rdp, "finish_push_attempt")
    status_changed = mocker.patch(f"{MOD}.rdp_push_status_changed_signal.send")

    _fail_pending_push(rdp_id=rdp.pk, push_attempt_id=push_attempt_id, hope_rdi_id=fallback_rdi_id)

    finish.assert_called_once_with(
        status=Rdp.PushStatus.FAILURE,
        hope_rdi_id=expected_rdi_id,
    )
    status_changed.assert_called_once_with(
        sender=Rdp,
        program_id=rdp.program_id,
        rdp_id=rdp.pk,
        status=Rdp.PushStatus.FAILURE,
    )
    assert run_on_commit.call_args.kwargs == {"robust": True}


@pytest.mark.parametrize(
    "case",
    [
        (True, "OLD-RDI", True),
        (False, None, True),
        (False, "RID", False),
    ],
    ids=["created", "existing_unstarted", "already_started"],
)
def test_schedule_push_data(rdp: Rdp, push_attempt_id: UUID, mocker: MockerFixture, run_on_commit, case) -> None:
    created, hope_rdi_id, scheduled = case
    rdp.hope_rdi_id = hope_rdi_id
    job = mocker.MagicMock()
    save = mocker.patch.object(rdp, "save")

    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)
    get_job = mocker.patch(f"{MOD}.get_or_create_rdp_push_data_job", return_value=(job, created))

    result = _schedule_push_data(rdp_id=rdp.pk, push_attempt_id=push_attempt_id)

    assert (result is job) is scheduled
    get_job.assert_called_once_with(
        rdp=rdp,
        push_attempt_id=push_attempt_id,
        action=fqn(push_rdp_data_core),
    )

    if created:
        assert rdp.hope_rdi_id is None
        save.assert_called_once_with(update_fields=["hope_rdi_id"])
    else:
        save.assert_not_called()

    if scheduled:
        job.queue.assert_called_once_with()
    else:
        job.queue.assert_not_called()


def test_schedule_push_data_ignores_stale_attempt(rdp: Rdp, push_attempt_id: UUID, mocker: MockerFixture) -> None:
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=None)
    get_job = mocker.patch(f"{MOD}.get_or_create_rdp_push_data_job")

    assert _schedule_push_data(rdp_id=rdp.pk, push_attempt_id=push_attempt_id) is None
    get_job.assert_not_called()


def test_claim_rdp_push_policy_denied(rdp: Rdp, mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.start_push_check.return_value = ActionCheck(False, "blocked")
    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update")

    check, locked = claim_rdp_push(rdp_id=rdp.pk)

    assert check.allowed is False
    assert locked is None
    lock.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        (Rdp.PushStatus.PENDING, False, True),
        (Rdp.PushStatus.FAILURE, False, True),
        (Rdp.PushStatus.PUSH_PENDING, False, False),
        (Rdp.PushStatus.PENDING, True, False),
        (Rdp.PushStatus.SUCCESS, False, False),
    ],
    ids=["pending", "failure", "already_pending", "dedup_locked", "terminal"],
)
def test_claim_rdp_push_rechecks_locked_rdp(rdp: Rdp, mocker: MockerFixture, case) -> None:
    status, dedup_locked, allowed = case
    rdp.status = status
    rdp.is_dedup_settings_locked = dedup_locked

    policy = mocker.MagicMock()
    policy.start_push_check.return_value = ActionCheck(True)
    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    start = mocker.patch.object(rdp, "start_push_attempt")

    check, claimed = claim_rdp_push(rdp_id=rdp.pk)

    assert check.allowed is allowed
    assert (claimed is rdp) is allowed
    assert start.called is allowed


@pytest.mark.parametrize("scheduled", [True, False], ids=["queued", "skipped"])
def test_push_preparation_without_previous_rdi(
    rdp: Rdp, preparation_job: AsyncJob, mocker: MockerFixture, scheduled: bool
) -> None:
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)
    hope_api = mocker.patch(f"{MOD}.HopeApi")
    mocker.patch(f"{MOD}._schedule_push_data", return_value=mocker.MagicMock() if scheduled else None)

    result = push_existing_rdp_core(preparation_job)

    assert result == {
        "rdp_id": rdp.pk,
        "reset_result": None,
        "workflow_outcome": (
            RdpWorkflowOutcome.DATA_PUSH_QUEUED if scheduled else RdpWorkflowOutcome.DATA_PUSH_SKIPPED
        ),
    }
    hope_api.assert_not_called()


def test_push_preparation_rejects_stale_attempt(preparation_job: AsyncJob, mocker: MockerFixture) -> None:
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=None)
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    with pytest.raises(RdpWorkflowError) as exc_info:
        push_existing_rdp_core(preparation_job)

    assert "no longer current" in str(exc_info.value)
    fail.assert_called_once()


@pytest.mark.parametrize(
    "case",
    [
        (RdiResetResult.ACCEPTED, RdpWorkflowOutcome.AWAITING_PUSH_READY_CALLBACK),
        (RdiResetResult.NOT_FOUND, RdpWorkflowOutcome.DATA_PUSH_QUEUED),
    ],
    ids=["accepted", "not_found"],
)
def test_push_preparation_reset(rdp: Rdp, preparation_job: AsyncJob, mocker: MockerFixture, case) -> None:
    reset_result, expected_outcome = case
    preparation_job.config["rdi_id_to_reset"] = "OLD-RDI"

    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)
    mocker.patch(f"{MOD}._build_push_ready_callback_url", return_value="callback")
    api = mocker.MagicMock()
    api.reset_rdi.return_value = reset_result
    mocker.patch(f"{MOD}.HopeApi", return_value=api)
    schedule = mocker.patch(f"{MOD}._schedule_push_data", return_value=mocker.MagicMock())

    result = push_existing_rdp_core(preparation_job)

    assert result["reset_result"] == reset_result.value
    assert result["workflow_outcome"] is expected_outcome
    assert schedule.called is (reset_result is RdiResetResult.NOT_FOUND)


def test_push_preparation_waits_when_reset_is_unconfirmed(
    rdp: Rdp, preparation_job: AsyncJob, mocker: MockerFixture
) -> None:
    preparation_job.config["rdi_id_to_reset"] = "OLD-RDI"
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)

    api = mocker.MagicMock()
    api.reset_rdi.side_effect = HopeRdiResetUnconfirmedError("boom")
    mocker.patch(f"{MOD}.HopeApi", return_value=api)
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    result = push_existing_rdp_core(preparation_job)

    assert result["workflow_outcome"] is RdpWorkflowOutcome.AWAITING_PUSH_READY_CALLBACK
    fail.assert_not_called()


def test_push_preparation_fails_on_unexpected_error(rdp: Rdp, preparation_job: AsyncJob, mocker: MockerFixture) -> None:
    preparation_job.config["rdi_id_to_reset"] = "OLD-RDI"
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)

    api = mocker.MagicMock()
    api.reset_rdi.side_effect = RuntimeError("boom")
    mocker.patch(f"{MOD}.HopeApi", return_value=api)
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    with pytest.raises(RdpWorkflowError) as exc_info:
        push_existing_rdp_core(preparation_job)

    assert "boom" in str(exc_info.value)
    fail.assert_called_once()


def test_push_preparation_fails_when_merge_is_in_progress(
    rdp: Rdp,
    preparation_job: AsyncJob,
    push_attempt_id: UUID,
    mocker: MockerFixture,
) -> None:
    preparation_job.config["rdi_id_to_reset"] = "OLD-RDI"
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)
    mocker.patch(f"{MOD}._build_push_ready_callback_url", return_value="callback")

    api = mocker.MagicMock()
    api.reset_rdi.return_value = RdiResetResult.MERGE_IN_PROGRESS
    mocker.patch(f"{MOD}.HopeApi", return_value=api)

    fail = mocker.patch(f"{MOD}._fail_pending_push")
    schedule = mocker.patch(f"{MOD}._schedule_push_data")

    with pytest.raises(RdpWorkflowError) as exc_info:
        push_existing_rdp_core(preparation_job)

    assert "merge is in progress" in str(exc_info.value)
    fail.assert_called_once_with(
        rdp_id=rdp.pk,
        push_attempt_id=push_attempt_id,
        hope_rdi_id="OLD-RDI",
    )
    schedule.assert_not_called()


@pytest.mark.parametrize("scheduled", [True, False], ids=["scheduled", "stale"])
def test_handle_push_ready_callback(push_attempt_id: UUID, mocker: MockerFixture, scheduled: bool) -> None:
    mocker.patch(f"{MOD}._schedule_push_data", return_value=mocker.MagicMock() if scheduled else None)

    assert handle_push_ready_callback(rdp_id=7, push_attempt_id=push_attempt_id) is scheduled


def test_handle_push_ready_callback_fails_attempt_on_error(push_attempt_id: UUID, mocker: MockerFixture) -> None:
    mocker.patch(f"{MOD}._schedule_push_data", side_effect=RuntimeError("boom"))
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    with pytest.raises(RuntimeError, match="boom"):
        handle_push_ready_callback(rdp_id=7, push_attempt_id=push_attempt_id)

    fail.assert_called_once()


@pytest.mark.parametrize("master_detail", [True, False], ids=["households", "people"])
def test_push_data_steps(mocker: MockerFixture, master_detail: bool) -> None:
    processor = mocker.MagicMock()
    individuals_for_push = mocker.patch(f"{MOD}.qs_individuals_for_push")
    households = mocker.patch(f"{MOD}.qs_households")
    people = mocker.patch(f"{MOD}.qs_individuals_by_pks")
    config = {
        "batch_name": "RDP",
        "co_slug": "co",
        "imported_by_email": "user@example.org",
        "master_detail": master_detail,
        "pks": [1, 2],
        "program_hope_id": "PROGRAM",
        "rdp_id": 7,
    }

    for step in _push_data_steps(processor, config):
        step()

    processor.rdi_complete.assert_called_once_with()

    if master_detail:
        individuals_for_push.assert_called_once_with([1, 2])
        households.assert_called_once_with(pks=[1, 2])
        people.assert_not_called()
        assert processor.run_with.call_count == 2
    else:
        people.assert_called_once_with([1, 2])
        individuals_for_push.assert_not_called()
        households.assert_not_called()
        processor.run_with.assert_called_once()


def test_push_data_skips_non_current_attempt(data_job: AsyncJob, mocker: MockerFixture) -> None:
    mocker.patch(f"{MOD}.claim_rdp_data_push", return_value=None)
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    result = push_rdp_data_core(data_job)

    assert result["workflow_outcome"] is RdpWorkflowOutcome.DATA_PUSH_SKIPPED
    fail.assert_not_called()


@pytest.mark.parametrize("owner_email", ["owner@example.org", ""], ids=["owner_email", "rdp_email"])
def test_push_data_success(push_data_setup, mocker: MockerFixture, run_on_commit, owner_email: str) -> None:
    rdp, job, processor, build_config = push_data_setup
    rdp.pushed_by.email = "rdp@example.org"
    rdp.deduplication_set_id = uuid4()
    job.owner.email = owner_email
    processor.total = {"people": 2}

    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)
    mark_removed = mocker.patch(f"{MOD}.set_rdp_beneficiaries_removed")
    finish = mocker.patch.object(rdp, "finish_push_attempt")
    approve = mocker.patch(f"{MOD}.approve_deduplication_set_after_successful_push")
    completed = mocker.patch(f"{MOD}.rdi_push_completed_signal.send_robust")
    status_changed = mocker.patch(f"{MOD}.rdp_push_status_changed_signal.send_robust")

    assert push_rdp_data_core(job) == {"people": 2}

    build_config.assert_called_once_with(rdp=rdp, imported_by_email=owner_email or rdp.pushed_by.email)
    processor.preflight.assert_called_once_with()
    processor.rdi_create.assert_called_once_with()
    processor.rdi_complete.assert_called_once_with()
    mark_removed.assert_called_once_with(rdp=rdp, removed=True)
    finish.assert_called_once_with(status=Rdp.PushStatus.SUCCESS, hope_rdi_id="NEW-RDI")
    approve.assert_called_once_with(
        rdp_id=rdp.pk,
        group_reference_id=rdp.program.unicef_id,
        deduplication_set_id=rdp.deduplication_set_id,
    )
    completed.assert_called_once_with(sender=Rdp, program_id=rdp.program_id, pushed_count=2)
    status_changed.assert_called_once()


@pytest.mark.parametrize(
    "case",
    [
        ("missing_rdi", AssertionError, "did not set hope_rdi_id"),
        ("changed_after_create", RdpWorkflowError, "while creating the new RDI"),
        ("changed_before_completion", RdpWorkflowError, "before completion"),
        ("changed_rdi", RuntimeError, "hope_rdi_id changed"),
    ],
    ids=["missing_rdi", "changed_after_create", "changed_before_completion", "changed_rdi"],
)
def test_push_data_rejects_invalid_state(push_data_setup, mocker: MockerFixture, case) -> None:
    rdp, job, processor, _ = push_data_setup
    scenario, exc_type, message = case
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    if scenario == "missing_rdi":
        processor.hope_rdi_id = None
    elif scenario == "changed_after_create":
        mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=None)
    elif scenario == "changed_before_completion":
        mocker.patch(f"{MOD}.lock_rdp_push_attempt", side_effect=[rdp, None])
    else:
        changed = mocker.MagicMock(hope_rdi_id="OTHER-RDI")
        mocker.patch(f"{MOD}.lock_rdp_push_attempt", side_effect=[rdp, changed])

    with pytest.raises(exc_type) as exc_info:
        push_rdp_data_core(job)

    assert message in str(exc_info.value)
    fail.assert_called_once()


def test_push_data_failure_fails_active_attempt(push_data_setup, mocker: MockerFixture) -> None:
    _, job, processor, _ = push_data_setup
    processor.has_errors = True
    processor.hope_rdi_id = None
    processor.total = {"errors": ["invalid data"]}
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    with pytest.raises(RdpWorkflowError):
        push_rdp_data_core(job)

    fail.assert_called_once()


def test_push_data_failure_before_processor(rdp: Rdp, data_job: AsyncJob, mocker: MockerFixture) -> None:
    mocker.patch(f"{MOD}.claim_rdp_data_push", return_value=rdp)
    mocker.patch(f"{MOD}._workflow_config_for_rdp", side_effect=RuntimeError("boom"))
    fail = mocker.patch(f"{MOD}._fail_pending_push")

    with pytest.raises(RuntimeError, match="boom"):
        push_rdp_data_core(data_job)

    fail.assert_called_once_with(
        rdp_id=rdp.pk,
        push_attempt_id=UUID(data_job.config["push_attempt_id"]),
        hope_rdi_id=None,
    )


def test_push_preparation_finishes_success_when_rdi_is_already_merged(
    rdp: Rdp,
    preparation_job: AsyncJob,
    push_attempt_id: UUID,
    mocker: MockerFixture,
    run_on_commit,
) -> None:
    preparation_job.config["rdi_id_to_reset"] = "OLD-RDI"
    mocker.patch(f"{MOD}.lock_rdp_push_attempt", return_value=rdp)
    mocker.patch(f"{MOD}._build_push_ready_callback_url", return_value="callback")

    api = mocker.MagicMock()
    api.reset_rdi.return_value = RdiResetResult.ALREADY_MERGED
    mocker.patch(f"{MOD}.HopeApi", return_value=api)

    mark_removed = mocker.patch(f"{MOD}.set_rdp_beneficiaries_removed")
    finish = mocker.patch.object(rdp, "finish_push_attempt")
    approve = mocker.patch(f"{MOD}.approve_deduplication_set_after_successful_push")
    schedule = mocker.patch(f"{MOD}._schedule_push_data")
    completed = mocker.patch(f"{MOD}.rdi_push_completed_signal.send_robust")
    status_changed = mocker.patch(f"{MOD}.rdp_push_status_changed_signal.send_robust")

    result = push_existing_rdp_core(preparation_job)

    assert result == {
        "rdp_id": rdp.pk,
        "reset_result": RdiResetResult.ALREADY_MERGED.value,
        "workflow_outcome": RdpWorkflowOutcome.DATA_PUSH_SKIPPED,
    }

    mark_removed.assert_called_once_with(rdp=rdp, removed=True)
    finish.assert_called_once_with(
        status=Rdp.PushStatus.SUCCESS,
        hope_rdi_id="OLD-RDI",
    )
    approve.assert_called_once_with(
        rdp_id=rdp.pk,
        group_reference_id=rdp.program.unicef_id,
        deduplication_set_id=rdp.deduplication_set_id,
    )
    status_changed.assert_called_once_with(
        sender=Rdp,
        program_id=rdp.program_id,
        rdp_id=rdp.pk,
        status=Rdp.PushStatus.SUCCESS,
    )

    schedule.assert_not_called()
    completed.assert_not_called()
