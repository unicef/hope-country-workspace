from collections.abc import Callable
from uuid import uuid4

import pytest
from django.db import IntegrityError
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.contrib.hope.exceptions import RdpWorkflowError
from country_workspace.contrib.hope.push.config import Beneficiary
from country_workspace.contrib.hope.push.orchestration import (
    _approve_deduplication_set_after_successful_push,
    _mark_rdp_beneficiaries_removed,
    _require_policy_check,
    _steps,
    cancel_existing_rdp_core,
    claim_rdp_deduplication,
    claim_rdp_push,
    create_rdp_core,
    create_and_push_rdp_core,
    dedup_existing_rdp_core,
    push_existing_rdp_core,
)
from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.workspaces.models import CountryHousehold

MOD = "country_workspace.contrib.hope.push.orchestration"

pytestmark = pytest.mark.django_db


@pytest.fixture
def proc() -> object:
    class Proc:
        def __init__(self) -> None:
            self.calls: list[object] = []
            self.rdi_already_merged = False

        def preflight(self) -> None:
            self.calls.append("pre")

        def rdi_create(self) -> None:
            self.calls.append("create")

        def rdi_complete(self) -> None:
            self.calls.append("complete")

        def rdi_push_individuals(self) -> None:
            self.calls.append("push_inds")

        def rdi_push_households(self) -> None:
            self.calls.append("push_hhs")

        def rdi_push_people(self) -> None:
            self.calls.append("push_people")

        def run_with(self, qs: object, step: Callable[[], None]) -> None:
            self.calls.append(("run_with", qs, step.__name__))

    return Proc()


def test_require_policy_check_calls_check_require(mocker: MockerFixture) -> None:
    check = mocker.MagicMock()
    check_fn = mocker.Mock(return_value=check)

    _require_policy_check(check_fn)

    check_fn.assert_called_once_with()
    check.require.assert_called_once_with()


def test_require_policy_check_propagates_denial(mocker: MockerFixture, err_contains) -> None:
    check_fn = mocker.Mock(return_value=ActionCheck(False, "blocked"))

    with pytest.raises(RdpWorkflowError) as exc:
        _require_policy_check(check_fn)

    assert err_contains(exc.value.args[0]["errors"], "blocked")
    check_fn.assert_called_once_with()


@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_require_policy_check_wraps_remote_errors(
    mocker: MockerFixture,
    exc_cls: type[Exception],
    err_contains,
) -> None:
    check = mocker.MagicMock()
    check.require.side_effect = exc_cls("boom")
    check_fn = mocker.Mock(return_value=check)

    with pytest.raises(RdpWorkflowError) as exc:
        _require_policy_check(check_fn)

    assert err_contains(exc.value.args[0]["errors"], "boom")


def test_create_rdp_core_requires_beneficiary_group(mocker: MockerFixture, err_contains) -> None:
    job = mocker.MagicMock(
        program=mocker.MagicMock(beneficiary_group=None, biometric_deduplication_enabled=False),
    )
    with pytest.raises(RdpWorkflowError) as exc:
        create_rdp_core(job)
    assert err_contains(exc.value.args[0]["errors"], "beneficiary_group is not set")


def test_create_rdp_core_preflight_errors(
    mocker: MockerFixture,
    create_job: AsyncJob,
    err_contains,
) -> None:
    create_job.program.biometric_deduplication_enabled = True
    make_client = mocker.patch(f"{MOD}.make_dedup_client")
    mocker.patch(f"{MOD}.preflight_errors", return_value=["boom"])

    with pytest.raises(RdpWorkflowError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "boom")
    make_client.assert_not_called()


def test_create_rdp_core_dedup_guard(
    mocker: MockerFixture,
    create_job: AsyncJob,
    dedup_api_cm,
    err_contains,
) -> None:
    create_job.program.biometric_deduplication_enabled = True
    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = False
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    with pytest.raises(RdpWorkflowError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "can not create deduplication set")


@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_create_rdp_core_dedup_remote_error(
    mocker: MockerFixture,
    create_job: AsyncJob,
    dedup_api_cm,
    exc_cls: type[Exception],
    err_contains,
) -> None:
    create_job.program.biometric_deduplication_enabled = True
    client = mocker.MagicMock()
    client.can_create_deduplication_set.side_effect = exc_cls("boom")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    with pytest.raises(RdpWorkflowError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "boom")


@pytest.mark.parametrize(
    ("db_error", "expected"),
    [
        ("boom", "can not create record"),
        ("uniq_open_rdp_per_program", "can not create while another RDP is open"),
    ],
    ids=["generic_integrity_error", "open_constraint"],
)
def test_create_rdp_core_integrity_error(
    mocker: MockerFixture,
    create_job: AsyncJob,
    err_contains,
    db_error: str,
    expected: str,
) -> None:
    create_job.program.biometric_deduplication_enabled = False
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch.object(Rdp.objects, "create", side_effect=IntegrityError(db_error))

    with pytest.raises(RdpWorkflowError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], expected)


@pytest.mark.parametrize("dedup_enabled", [False, True], ids=["dedup_off", "dedup_on"])
def test_create_rdp_core_success(
    mocker: MockerFixture,
    create_job: AsyncJob,
    dedup_api_cm,
    dedup_enabled: bool,
) -> None:
    create_job.program.biometric_deduplication_enabled = dedup_enabled
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    client = mocker.MagicMock()
    client.can_create_deduplication_set.return_value = True
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    out = create_rdp_core(create_job)

    create_job.refresh_from_db()
    assert out == {"rdp_id": create_job.rdp_id, "rdp_str": str(create_job.rdp)}
    assert make_client.called is dedup_enabled
    assert client.can_create_deduplication_set.called is dedup_enabled


def test_create_and_push_rdp_core_routes_to_dedup_flow(mocker: MockerFixture) -> None:
    job = mocker.MagicMock()
    job.program.biometric_deduplication_enabled = True
    dedup_flow = mocker.patch(f"{MOD}.create_rdp_and_start_dedup_core", return_value={"dedup_pending": True})

    assert create_and_push_rdp_core(job) == {"dedup_pending": True}

    dedup_flow.assert_called_once_with(job)


def test_create_and_push_rdp_core_requires_biometric(mocker: MockerFixture) -> None:
    job = mocker.MagicMock()
    job.program.biometric_deduplication_enabled = False
    dedup_flow = mocker.patch(f"{MOD}.create_rdp_and_start_dedup_core")

    with pytest.raises(RdpWorkflowError):
        create_and_push_rdp_core(job)

    dedup_flow.assert_not_called()


@pytest.mark.parametrize(
    ("set_id", "can_create", "expect_generated_id", "expected_update_fields"),
    [
        ("ds-1", True, False, ["is_dedup_settings_locked"]),
        ("ds-1", False, False, ["is_dedup_settings_locked"]),
        (None, True, True, ["is_dedup_settings_locked", "deduplication_set_id"]),
        (None, False, False, ["is_dedup_settings_locked"]),
    ],
    ids=["keeps_existing_set", "keeps_existing_active_set", "generates_new_set_id", "no_set_id"],
)
def test_claim_rdp_deduplication_locks_rdp(
    mocker: MockerFixture,
    set_id: str | None,
    can_create: bool,
    expect_generated_id: bool,
    expected_update_fields: list[str],
) -> None:
    generated_id = uuid4()
    rdp = mocker.MagicMock(deduplication_set_id=set_id, is_dedup_settings_locked=False)
    policy = mocker.MagicMock(can_create_deduplication_set=can_create)
    policy.deduplicate_check.return_value = ActionCheck(True)

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    get_policy = mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    uuid4_spy = mocker.patch(f"{MOD}.uuid4", return_value=generated_id)

    check, locked = claim_rdp_deduplication(123)

    assert check == ActionCheck(True)
    assert locked is rdp
    assert rdp.is_dedup_settings_locked is True
    assert rdp.deduplication_set_id == (generated_id if expect_generated_id else set_id)
    lock.assert_called_once_with(pk=123)
    get_policy.assert_called_once_with(rdp)
    policy.deduplicate_check.assert_called_once_with()
    rdp.save.assert_called_once_with(update_fields=expected_update_fields)
    assert uuid4_spy.called is expect_generated_id


def test_claim_rdp_deduplication_returns_denial_without_locking(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock()
    denied = ActionCheck(False, "blocked")
    policy = mocker.MagicMock()
    policy.deduplicate_check.return_value = denied

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update")
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    assert claim_rdp_deduplication(123) == (denied, None)
    lock.assert_not_called()


def test_claim_rdp_deduplication_returns_denial_when_already_locked(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(is_dedup_settings_locked=True)
    policy = mocker.MagicMock()
    policy.deduplicate_check.return_value = ActionCheck(True)

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    check, locked = claim_rdp_deduplication(123)

    assert check.allowed is False
    assert "already been started" in check.reason
    assert locked is None
    rdp.save.assert_not_called()


@pytest.mark.parametrize("status", [Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE])
def test_claim_rdp_push_locks_rdp(mocker: MockerFixture, status: str) -> None:
    rdp = mocker.MagicMock(is_push_locked=False, status=status)
    rdp.PushStatus = Rdp.PushStatus
    policy = mocker.MagicMock()
    policy.start_push_check.return_value = ActionCheck(True)

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    assert claim_rdp_push(123) == (ActionCheck(True), rdp)
    assert rdp.is_push_locked is True
    rdp.save.assert_called_once_with(update_fields=["is_push_locked"])


def test_claim_rdp_push_returns_denial_without_locking(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock()
    denied = ActionCheck(False, "blocked")
    policy = mocker.MagicMock()
    policy.start_push_check.return_value = denied

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update")
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    assert claim_rdp_push(123) == (denied, None)
    lock.assert_not_called()


@pytest.mark.parametrize(
    ("is_push_locked", "status", "expected"),
    [
        (True, Rdp.PushStatus.PENDING, "already queued or running"),
        (False, Rdp.PushStatus.SUCCESS, "can not push in status"),
    ],
    ids=["already_locked", "wrong_status"],
)
def test_claim_rdp_push_rejects_locked_or_wrong_status(
    mocker: MockerFixture,
    is_push_locked: bool,
    status: str,
    expected: str,
) -> None:
    rdp = mocker.MagicMock(is_push_locked=is_push_locked, status=status)
    rdp.PushStatus = Rdp.PushStatus
    policy = mocker.MagicMock()
    policy.start_push_check.return_value = ActionCheck(True)

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    check, locked = claim_rdp_push(123)

    assert check.allowed is False
    assert expected in check.reason
    assert locked is None
    rdp.save.assert_not_called()


@pytest.mark.parametrize("has_errors", [False, True], ids=["success", "failure"])
def test_dedup_existing_rdp_core(
    mocker: MockerFixture,
    dedup_api_cm,
    has_errors: bool,
    err_contains,
) -> None:
    rdp = mocker.MagicMock(pk=1)
    rdp.program.unicef_id = "program-1"
    policy = mocker.MagicMock()
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    total = {"images_sent": 2, "errors": ["boom"] if has_errors else []}
    processor = mocker.MagicMock(total=total, has_errors=has_errors)
    processor.rdp.deduplication_set_id = uuid4()
    job = mocker.MagicMock(pk=7, config={"rdp_id": 123})
    locked = mocker.MagicMock()
    client = mocker.MagicMock()
    client.get_deduplication_set_group_config.return_value = {"threshold": 0.8}

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    require = mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    processor_cls = mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    append_log = mocker.patch(f"{MOD}.append_rdp_operation_log")
    release = mocker.patch(f"{MOD}.release_rdp_dedup_settings_lock")

    if has_errors:
        with pytest.raises(RdpWorkflowError) as exc:
            dedup_existing_rdp_core(job)
        assert err_contains(exc.value.args[0]["errors"], "boom")
    else:
        assert dedup_existing_rdp_core(job) == total

    require.assert_called_once_with(policy.deduplicate_check)
    client.get_deduplication_set_group_config.assert_called_once_with()
    processor_cls.assert_called_once_with(rdp)
    processor.run.assert_called_once_with()
    append_log.assert_called_once()
    assert append_log.call_args.kwargs["rdp"] is locked
    assert append_log.call_args.kwargs["action"] == Rdp.OperationAction.START_DEDUPLICATION
    assert append_log.call_args.kwargs["job_id"] == 7
    assert append_log.call_args.kwargs["result"]["dedup_settings"] == {"threshold": 0.8}
    release.assert_called_once_with(rdp_id=123)


@pytest.mark.parametrize(
    ("set_id", "state", "expected_rejected"),
    [
        ("ds-1", DeduplicationSetState.DEDUPLICATED, True),
        ("ds-1", DeduplicationSetState.REJECTED, False),
        (None, DeduplicationSetState.DEDUPLICATED, False),
    ],
    ids=["rejectable_set", "non_rejectable_set", "no_set"],
)
def test_cancel_existing_rdp_core(
    mocker: MockerFixture,
    dedup_api_cm,
    set_id: str | None,
    state: DeduplicationSetState,
    expected_rejected: bool,
) -> None:
    program = mocker.MagicMock(unicef_id="program-1")
    rdp = mocker.MagicMock(pk=1, deduplication_set_id=set_id, program=program)
    locked = mocker.MagicMock(hope_rdi_id="")
    policy = mocker.MagicMock(deduplication_set_state=state)
    client = mocker.MagicMock()

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    require = mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    assert cancel_existing_rdp_core(mocker.MagicMock(config={"rdp_id": 1})) == {
        "rdp_id": 1,
        "program": "program-1",
        "deduplication_set_id": set_id,
        "dedup_engine_rejected": expected_rejected,
        "cancelled": True,
    }

    require.assert_called_once_with(policy.cancel_check)
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.CANCELLED,
        hope_rdi_id="N/A",
        is_dedup_settings_locked=False,
        is_push_locked=False,
    )
    assert make_client.called is expected_rejected
    assert client.reject.called is expected_rejected


@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_cancel_existing_rdp_core_wraps_reject_errors(
    mocker: MockerFixture,
    dedup_api_cm,
    exc_cls: type[Exception],
    err_contains,
) -> None:
    program = mocker.MagicMock(unicef_id="program-1")
    rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1", program=program)
    policy = mocker.MagicMock(deduplication_set_state=DeduplicationSetState.DEDUPLICATED)
    client = mocker.MagicMock()
    client.reject.side_effect = exc_cls("boom")

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    with pytest.raises(RdpWorkflowError) as exc:
        cancel_existing_rdp_core(mocker.MagicMock(config={"rdp_id": 1}))

    assert err_contains(exc.value.args[0]["errors"], "boom")
    set_status.assert_not_called()


def test_approve_deduplication_set_after_successful_push_without_set_id(mocker: MockerFixture) -> None:
    processor = mocker.MagicMock()
    make_client = mocker.patch(f"{MOD}.make_dedup_client")

    _approve_deduplication_set_after_successful_push(
        group_reference_id="program-1",
        deduplication_set_id=None,
        processor=processor,
    )

    make_client.assert_not_called()
    processor.fail.assert_not_called()


def test_approve_deduplication_set_after_successful_push(mocker: MockerFixture, dedup_api_cm) -> None:
    processor = mocker.MagicMock()
    client = mocker.MagicMock()
    ds_id = uuid4()
    make_client = mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    _approve_deduplication_set_after_successful_push(
        group_reference_id="program-1",
        deduplication_set_id=ds_id,
        processor=processor,
    )

    make_client.assert_called_once_with("program-1", deduplication_set_id=str(ds_id))
    client.approve.assert_called_once_with()
    processor.fail.assert_not_called()


@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_approve_deduplication_set_after_successful_push_records_error(
    mocker: MockerFixture,
    dedup_api_cm,
    exc_cls: type[Exception],
) -> None:
    processor = mocker.MagicMock()
    client = mocker.MagicMock()
    client.approve.side_effect = exc_cls("boom")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    _approve_deduplication_set_after_successful_push(
        group_reference_id="program-1",
        deduplication_set_id=uuid4(),
        processor=processor,
    )

    processor.fail.assert_called_once()
    assert processor.fail.call_args.args[0] == "DedupEngine"
    assert "approve failed" in processor.fail.call_args.args[1]
    assert "boom" in processor.fail.call_args.args[1]


def test_mark_rdp_beneficiaries_removed(job: AsyncJob, beneficiary_instance: Beneficiary) -> None:
    _mark_rdp_beneficiaries_removed(job.rdp, job.program.beneficiary_group.master_detail)

    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.removed is True
    if isinstance(beneficiary_instance, CountryHousehold):
        assert all(member.removed for member in beneficiary_instance.members.all())


def test_mark_rdp_beneficiaries_removed_empty_master_detail(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock()
    rdp.households.values_list.return_value = []
    qs_inds = mocker.patch(f"{MOD}.qs_individuals_by_household_pks")

    _mark_rdp_beneficiaries_removed(rdp, True)

    rdp.households.update.assert_not_called()
    qs_inds.assert_not_called()


@pytest.mark.parametrize("master_detail", [True, False], ids=["master_detail", "flat"])
def test_steps(master_detail: bool, mocker: MockerFixture, proc: object) -> None:
    config = {"pks": [1, 2], "master_detail": master_detail}
    qs_by_hh = mocker.patch(f"{MOD}.qs_individuals_for_push", return_value="ind_qs")
    qs_hh = mocker.patch(f"{MOD}.qs_households", return_value="hh_qs")
    qs_by_pks = mocker.patch(f"{MOD}.qs_individuals_by_pks", return_value="people_qs")

    for step in _steps(proc, config):
        step()

    if master_detail:
        assert proc.calls == [
            "pre",
            "create",
            ("run_with", "ind_qs", "rdi_push_individuals"),
            ("run_with", "hh_qs", "rdi_push_households"),
            "complete",
        ]
        qs_by_hh.assert_called_once_with([1, 2])
        qs_hh.assert_called_once_with(pks=[1, 2])
        qs_by_pks.assert_not_called()
    else:
        assert proc.calls == [
            "pre",
            "create",
            ("run_with", "people_qs", "rdi_push_people"),
            "complete",
        ]
        qs_by_pks.assert_called_once_with([1, 2])
        qs_by_hh.assert_not_called()
        qs_hh.assert_not_called()


def test_steps_stop_for_already_merged_rdi(mocker: MockerFixture, proc: object) -> None:
    proc.rdi_already_merged = True
    qs_by_hh = mocker.patch(f"{MOD}.qs_individuals_by_household_pks")
    qs_hh = mocker.patch(f"{MOD}.qs_households")
    qs_by_pks = mocker.patch(f"{MOD}.qs_individuals_by_pks")

    for step in _steps(proc, {"pks": [1], "master_detail": False}):
        step()

    assert proc.calls == ["pre", "create"]
    qs_by_hh.assert_not_called()
    qs_hh.assert_not_called()
    qs_by_pks.assert_not_called()


@pytest.mark.parametrize(
    ("owner_email", "pushed_by_email", "expected_email"),
    [
        ("owner@example.com", "pushed@example.com", "owner@example.com"),
        ("", "pushed@example.com", "pushed@example.com"),
    ],
    ids=["owner_email", "fallback_to_pushed_by"],
)
def test_push_existing_rdp_core_success(
    mocker: MockerFixture,
    owner_email: str,
    pushed_by_email: str,
    expected_email: str,
) -> None:
    rdp = mocker.MagicMock(pk=1)
    rdp.pushed_by.email = pushed_by_email
    policy = mocker.MagicMock()
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    locked = mocker.MagicMock(deduplication_set_id=(ds_id := uuid4()))
    locked.program.unicef_id = "program-1"
    config = {"master_detail": True, "pks": [1], "rdp_id": 1}
    processor = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id="RID-1", rdi_already_merged=False)
    step1 = mocker.Mock()
    step2 = mocker.Mock()
    job = mocker.MagicMock(config={"rdp_id": 1})
    job.owner.email = owner_email

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    require = mocker.patch(f"{MOD}._require_policy_check")
    workflow = mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    processor_cls = mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    steps_spy = mocker.patch(f"{MOD}._steps", return_value=[step1, step2])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    mark_removed = mocker.patch(f"{MOD}._mark_rdp_beneficiaries_removed")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    approve = mocker.patch(f"{MOD}._approve_deduplication_set_after_successful_push")
    release = mocker.patch(f"{MOD}.release_rdp_push_lock")
    rdi_pushed = mocker.patch(f"{MOD}.rdi_push_completed_signal.send")
    rdp_pushed = mocker.patch(f"{MOD}.rdp_push_status_changed_signal.send")

    assert push_existing_rdp_core(job) == {"errors": []}

    require.assert_called_once_with(policy.push_check)
    workflow.assert_called_once_with(rdp=rdp, imported_by_email=expected_email)
    processor_cls.assert_called_once_with(config)
    steps_spy.assert_called_once_with(processor, config)
    step1.assert_called_once_with()
    step2.assert_called_once_with()
    mark_removed.assert_called_once_with(locked, True)
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.SUCCESS,
        hope_rdi_id="RID-1",
        is_push_locked=False,
    )
    release.assert_called_once_with(rdp_id=1)
    approve.assert_called_once_with(
        group_reference_id="program-1",
        deduplication_set_id=ds_id,
        processor=processor,
    )
    rdi_pushed.assert_called_once_with(
        sender=Rdp,
        program_id=rdp.program_id,
        pushed_count=0,
    )
    rdp_pushed.assert_called_once_with(
        sender=Rdp,
        program_id=rdp.program_id,
        rdp_id=rdp.pk,
        status=Rdp.PushStatus.SUCCESS,
    )


def test_push_existing_rdp_core_already_merged_skips_rdi_push_completed(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(pk=1)
    rdp.pushed_by.email = "pushed@example.com"
    policy = mocker.MagicMock()
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    locked = mocker.MagicMock(deduplication_set_id=None)
    locked.program.unicef_id = "program-1"
    config = {"master_detail": True, "pks": [1], "rdp_id": 1}
    processor = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id="RID-1", rdi_already_merged=True)
    job = mocker.MagicMock(config={"rdp_id": 1})
    job.owner.email = "owner@example.com"

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    mocker.patch(f"{MOD}._steps", return_value=[])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    mocker.patch(f"{MOD}._mark_rdp_beneficiaries_removed")
    mocker.patch(f"{MOD}.set_rdp_push_status")
    mocker.patch(f"{MOD}._approve_deduplication_set_after_successful_push")
    mocker.patch(f"{MOD}.release_rdp_push_lock")
    rdi_pushed = mocker.patch(f"{MOD}.rdi_push_completed_signal.send")
    rdp_pushed = mocker.patch(f"{MOD}.rdp_push_status_changed_signal.send")

    assert push_existing_rdp_core(job) == {"errors": []}

    rdi_pushed.assert_not_called()
    rdp_pushed.assert_called_once_with(
        sender=Rdp,
        program_id=rdp.program_id,
        rdp_id=rdp.pk,
        status=Rdp.PushStatus.SUCCESS,
    )


def test_push_existing_rdp_core_failure(mocker: MockerFixture, err_contains) -> None:
    rdp = mocker.MagicMock(pk=1)
    rdp.pushed_by.email = "pushed@example.com"
    locked = mocker.MagicMock()
    config = {"master_detail": False, "pks": [1], "rdp_id": 1}
    processor = mocker.MagicMock(total={"errors": ["boom"]}, has_errors=False, hope_rdi_id=None)
    job = mocker.MagicMock(config={"rdp_id": 1})
    job.owner.email = ""

    def fail_step() -> None:
        processor.has_errors = True

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    policy = mocker.MagicMock()
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    require = mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    next_step = mocker.Mock()
    mocker.patch(f"{MOD}._steps", return_value=[fail_step, next_step])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    mark_removed = mocker.patch(f"{MOD}._mark_rdp_beneficiaries_removed")
    release = mocker.patch(f"{MOD}.release_rdp_push_lock")
    mocker.patch(
        f"{MOD}.transaction.on_commit",
        side_effect=lambda func, *, robust=False: func(),
    )
    rdi_pushed = mocker.patch(f"{MOD}.rdi_push_completed_signal.send")
    rdp_pushed = mocker.patch(f"{MOD}.rdp_push_status_changed_signal.send")

    with pytest.raises(RdpWorkflowError) as exc:
        push_existing_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "boom")
    mark_removed.assert_not_called()
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.FAILURE,
        hope_rdi_id="N/A",
        is_push_locked=False,
    )
    release.assert_called_once_with(rdp_id=1)
    rdi_pushed.assert_not_called()
    rdp_pushed.assert_called_once_with(
        sender=Rdp,
        program_id=rdp.program_id,
        rdp_id=rdp.pk,
        status=Rdp.PushStatus.FAILURE,
    )
    next_step.assert_not_called()
    require.assert_called_once_with(policy.push_check)
