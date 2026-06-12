from collections.abc import Callable
from uuid import uuid4

import pytest
from django.db import IntegrityError
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import (
    DedupClientStatus,
    DedupResponseStatus,
    DeduplicationSetState,
)
from country_workspace.contrib.hope.exceptions import (
    HopePushError,
    HopeRdiCallbackConflictError,
    HopeRdiCallbackError,
    HopeRdiCallbackNotFoundError,
)
from country_workspace.contrib.hope.push.config import Beneficiary, HopeRdiCallbackCode
from country_workspace.contrib.hope.push.orchestration import (
    _deduplication_snapshot,
    _mark_rdp_beneficiaries_removed,
    _restore_rdp_removed_beneficiaries,
    _require_policy_check,
    _save_current_deduplication_snapshot,
    _steps,
    apply_hope_rdi_final_status,
    claim_rdp_deduplication,
    clone_rdp_core,
    create_rdp_core,
    dedup_existing_rdp_core,
    push_existing_rdp_core,
    reject_deduplication_set_existing_rdp_core,
    reset_rdp_core,
)
from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, Rdp
from country_workspace.workspaces.models import CountryHousehold

MOD = "country_workspace.contrib.hope.push.orchestration"


@pytest.fixture
def proc() -> object:
    class Proc:
        def __init__(self) -> None:
            self.calls: list[object] = []

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


@pytest.fixture
def mock_dedup_status(mocker: MockerFixture):
    def factory(
        state: DeduplicationSetState = DeduplicationSetState.DEDUPLICATED,
        *,
        response_status: DedupResponseStatus = DedupResponseStatus.OK,
    ):
        policy = mocker.MagicMock()
        policy.deduplication_status.return_value = DedupClientStatus(
            response_status=response_status,
            deduplication_set_status=state.value,
            findings_count=3,
        )
        mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
        return policy

    return factory


@pytest.fixture
def mock_clone_flow(mocker: MockerFixture):
    def factory(
        source,
        *,
        owner=None,
        has_pending: bool = False,
        errors: list[str] | None = None,
    ):
        owner = owner or source

        mocker.patch(f"{MOD}._require_policy_check")
        mocker.patch(f"{MOD}.selection_owner_for_rdp", side_effect=[owner, owner])
        mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
        mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
        mocker.patch(f"{MOD}.preflight_errors", return_value=errors or [])
        mocker.patch(f"{MOD}.lock_rdp_for_update", side_effect=[source, owner] if owner is not source else [source])
        mocker.patch(f"{MOD}.has_other_pending_rdp", return_value=has_pending)

        return owner

    return factory


@pytest.fixture
def mock_reject_flow(mocker: MockerFixture, dedup_api_cm):
    def factory(*, reject_error: Exception | None = None):
        program = mocker.MagicMock(unicef_id="program-1")
        rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1", hope_rdi_id="", program=program)
        locked = mocker.MagicMock(deduplication_set_id="ds-1", hope_rdi_id="")
        job = mocker.MagicMock(config={"rdp_id": 1})

        policy = mocker.MagicMock()
        policy.deduplication_status.return_value = DedupClientStatus(
            response_status=DedupResponseStatus.OK,
            deduplication_set_status=DeduplicationSetState.DEDUPLICATED.value,
            findings_count=3,
        )

        mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
        mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
        require = mocker.patch(f"{MOD}._require_policy_check")
        mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
        mocker.patch(f"{MOD}._deduplication_snapshot", return_value={"state": "Deduplicated"})

        client = mocker.MagicMock()
        if reject_error is not None:
            client.reject.side_effect = reject_error
        mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

        return job, rdp, locked, client, require

    return factory


def test_require_policy_check_calls_check_require(mocker: MockerFixture) -> None:
    check = mocker.MagicMock()
    check_fn = mocker.Mock(return_value=check)

    _require_policy_check(check_fn)

    check_fn.assert_called_once_with()
    check.require.assert_called_once_with()


def test_require_policy_check_propagates_denial(mocker: MockerFixture, err_contains) -> None:
    check_fn = mocker.Mock(return_value=ActionCheck(False, "blocked"))

    with pytest.raises(HopePushError) as exc:
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

    with pytest.raises(HopePushError) as exc:
        _require_policy_check(check_fn)

    assert err_contains(exc.value.args[0]["errors"], "boom")


def test_deduplication_snapshot_returns_empty_dict_without_status() -> None:
    assert _deduplication_snapshot(None) == {}


def test_deduplication_snapshot_returns_serializable_status(mocker: MockerFixture) -> None:
    status = mocker.MagicMock(
        deduplication_set_status=DeduplicationSetState.DEDUPLICATED,
        findings_count=7,
    )

    assert _deduplication_snapshot(status) == {
        "deduplication_set_status": DeduplicationSetState.DEDUPLICATED.value,
        "findings_count": 7,
    }


def test_save_current_deduplication_snapshot(
    mocker: MockerFixture,
) -> None:
    rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1")
    locked = mocker.MagicMock(deduplication_set_id="ds-1")
    status = mocker.MagicMock()

    policy = mocker.MagicMock()
    policy.deduplication_status.return_value = status

    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    snapshot_builder = mocker.patch(f"{MOD}._deduplication_snapshot", return_value={"state": "Deduplicated"})
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_snapshot = mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")

    _save_current_deduplication_snapshot(rdp=rdp, key="before_push")

    policy.deduplication_status.assert_called_once_with(rdp)
    snapshot_builder.assert_called_once_with(status)
    lock.assert_called_once_with(pk=1)
    set_snapshot.assert_called_once_with(
        rdp=locked,
        key="before_push",
        snapshot={"state": "Deduplicated"},
    )


def test_save_current_deduplication_snapshot_detects_changed_dedup_state(
    mocker: MockerFixture,
    err_contains,
) -> None:
    rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1")
    locked = mocker.MagicMock(deduplication_set_id="ds-2")

    policy = mocker.MagicMock()
    policy.deduplication_status.return_value = mocker.MagicMock()

    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    mocker.patch(f"{MOD}._deduplication_snapshot", return_value={"state": "Deduplicated"})
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_snapshot = mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")

    with pytest.raises(HopePushError) as exc:
        _save_current_deduplication_snapshot(rdp=rdp, key="before_push")

    assert err_contains(exc.value.args[0]["errors"], "deduplication state changed")
    set_snapshot.assert_not_called()


@pytest.mark.parametrize(
    ("beneficiary_group", "pks", "expected"),
    [
        (None, [1], "beneficiary_group is not set"),
        (object(), [], "no beneficiaries selected"),
    ],
    ids=["missing_group", "missing_pks"],
)
def test_create_rdp_core_guard_errors(
    mocker: MockerFixture,
    beneficiary_group: object | None,
    pks: list[int],
    expected: str,
    err_contains,
) -> None:
    job = mocker.MagicMock(
        program=mocker.MagicMock(beneficiary_group=beneficiary_group, biometric_deduplication_enabled=False),
        config={"pks": pks, "master_detail": True},
    )

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], expected)


@pytest.mark.django_db
def test_create_rdp_core_preflight_errors(
    mocker: MockerFixture,
    create_job: AsyncJob,
    err_contains,
) -> None:
    create_job.program.biometric_deduplication_enabled = True
    make_client = mocker.patch(f"{MOD}.make_dedup_client")
    mocker.patch(f"{MOD}.preflight_errors", return_value=["boom"])

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "boom")
    make_client.assert_not_called()


@pytest.mark.django_db
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

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "can not create deduplication set")


@pytest.mark.django_db
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

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "boom")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("db_error", "expected"),
    [
        ("boom", "can not create record"),
        ("uniq_pending_rdp_per_program", "another RDP is pending"),
    ],
    ids=["generic_integrity_error", "pending_constraint"],
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

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], expected)


@pytest.mark.django_db
def test_create_rdp_core_success(mocker: MockerFixture, create_job: AsyncJob) -> None:
    create_job.program.biometric_deduplication_enabled = False
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    out = create_rdp_core(create_job)

    create_job.refresh_from_db()
    assert out == {"rdp_id": create_job.rdp_id, "rdp_str": str(create_job.rdp)}


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
    rdp = mocker.MagicMock(deduplication_set_id=set_id)
    policy = mocker.MagicMock(can_create_deduplication_set=can_create)
    policy.claim_deduplication_check.return_value = ActionCheck(True)

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
    policy.claim_deduplication_check.assert_called_once_with()
    rdp.save.assert_called_once_with(update_fields=expected_update_fields)
    if expect_generated_id:
        uuid4_spy.assert_called_once_with()
    else:
        uuid4_spy.assert_not_called()


def test_claim_rdp_deduplication_returns_denial_without_saving(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(deduplication_set_id="ds-1")
    denied = ActionCheck(False, "blocked")
    policy = mocker.MagicMock()
    policy.claim_deduplication_check.return_value = denied

    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)

    assert claim_rdp_deduplication(123) == (denied, None)

    rdp.save.assert_not_called()


@pytest.mark.parametrize("has_errors", [False, True], ids=["success", "failure"])
def test_dedup_existing_rdp_core(
    mocker: MockerFixture,
    has_errors: bool,
    err_contains,
) -> None:
    rdp = mocker.MagicMock()
    total = {"errors": ["boom"]} if has_errors else {"errors": []}
    processor = mocker.MagicMock(total=total, has_errors=has_errors)
    job = mocker.MagicMock(config={"rdp_id": 123})

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    require = mocker.patch(f"{MOD}._require_policy_check")
    processor_cls = mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)

    if has_errors:
        with pytest.raises(HopePushError) as exc:
            dedup_existing_rdp_core(job)
        assert err_contains(exc.value.args[0]["errors"], "boom")
    else:
        assert dedup_existing_rdp_core(job) == total

    require.assert_called_once()
    processor_cls.assert_called_once_with(rdp)
    processor.run.assert_called_once_with()


def test_clone_rdp_core_preflight_errors(mocker: MockerFixture, err_contains) -> None:
    source = mocker.MagicMock()
    owner = mocker.MagicMock()

    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=["boom"])

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=1)

    assert err_contains(exc.value.args[0]["errors"], "boom")


def test_clone_rdp_core_requires_deduplication_set_id(
    mocker: MockerFixture,
    err_contains,
) -> None:
    source = mocker.MagicMock(deduplication_set_id=None)
    owner = mocker.MagicMock(deduplication_set_id=None)

    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=1)

    assert err_contains(exc.value.args[0]["errors"], "deduplication_set_id is not set")


@pytest.mark.parametrize(
    "status",
    [
        None,
        pytest.param(
            DedupClientStatus(
                response_status=DedupResponseStatus.STATUS_UNAVAILABLE,
                deduplication_set_status=None,
                findings_count=-1,
            ),
            id="status_unavailable",
        ),
    ],
    ids=["none", "status_unavailable"],
)
def test_clone_rdp_core_requires_available_deduplication_status(
    mocker: MockerFixture,
    status,
    err_contains,
) -> None:
    source = mocker.MagicMock(deduplication_set_id="ds-1")
    owner = source

    policy = mocker.MagicMock()
    policy.deduplication_status.return_value = status

    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.get_rdp_policy", return_value=policy)
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=1)

    assert err_contains(exc.value.args[0]["errors"], "can not retrieve deduplication set status")


def test_clone_rdp_core_detects_changed_dedup_state(
    mocker: MockerFixture,
    mock_dedup_status,
    err_contains,
) -> None:
    source = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id="ds-before",
    )
    locked = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id="ds-after",
    )

    mock_dedup_status()
    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", side_effect=[source, locked])
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    mocker.patch(f"{MOD}.has_other_pending_rdp", return_value=False)
    set_snapshot = mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")
    create = mocker.patch.object(Rdp.objects, "create")

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=7)

    assert err_contains(exc.value.args[0]["errors"], "deduplication state changed")
    set_snapshot.assert_not_called()
    create.assert_not_called()


def test_clone_rdp_core_blocks_when_other_pending_exists(
    mocker: MockerFixture,
    mock_dedup_status,
    mock_clone_flow,
    err_contains,
) -> None:
    source = mocker.MagicMock(pk=1, status=Rdp.PushStatus.PENDING, deduplication_set_id="ds-1")

    mock_dedup_status()
    mock_clone_flow(source, has_pending=True)

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=1)

    assert err_contains(exc.value.args[0]["errors"], "another RDP is pending")


def test_clone_rdp_core_blocks_merged_source_after_lock(
    mocker: MockerFixture,
    mock_dedup_status,
    err_contains,
) -> None:
    source = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id="ds-1",
    )
    locked = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.MERGED,
        deduplication_set_id="ds-1",
    )

    mock_dedup_status()
    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=source)
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    create = mocker.patch.object(Rdp.objects, "create")

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=7)

    assert err_contains(exc.value.args[0]["errors"], "can not clone a merged RDP")
    create.assert_not_called()


def test_clone_rdp_core_does_not_reuse_non_deduplicated_set(
    mocker: MockerFixture,
    mock_dedup_status,
    mock_clone_flow,
) -> None:
    source = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        country_office_id=10,
        program_id=20,
        deduplication_set_id="ds-1",
        is_dedup_settings_locked=False,
    )
    cloned = mocker.MagicMock()

    mock_dedup_status(DeduplicationSetState.REJECTED)
    mock_clone_flow(source)
    mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")
    create = mocker.patch.object(Rdp.objects, "create", return_value=cloned)

    assert clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=7) is cloned

    source.save.assert_called_once_with(update_fields=["status"])
    create.assert_called_once_with(
        country_office_id=10,
        program_id=20,
        pushed_by_id=7,
        name="Clone",
        parent=source,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id=None,
        is_dedup_settings_locked=False,
    )


@pytest.mark.parametrize(
    ("source_set_id", "owner_set_id", "expected_uses_owner", "expected_set_id"),
    [
        ("ds-source", None, False, "ds-source"),
        (None, "ds-owner", True, "ds-owner"),
    ],
    ids=["source_set", "owner_set"],
)
def test_clone_rdp_core_success_rejects_pending_source(
    mocker: MockerFixture,
    mock_dedup_status,
    mock_clone_flow,
    source_set_id: str | None,
    owner_set_id: str | None,
    expected_uses_owner: bool,
    expected_set_id: str,
) -> None:
    source = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        country_office_id=10,
        program_id=20,
        deduplication_set_id=source_set_id,
        is_dedup_settings_locked=True,
    )
    owner = mocker.MagicMock(
        pk=10,
        country_office_id=10,
        program_id=20,
        deduplication_set_id=owner_set_id,
    )
    cloned = mocker.MagicMock()

    policy = mock_dedup_status()
    owner = mock_clone_flow(source, owner=owner if owner_set_id else source)
    dedup_snapshot = mocker.patch(f"{MOD}._deduplication_snapshot", return_value={"state": "Deduplicated"})
    snapshot = mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")
    create = mocker.patch.object(Rdp.objects, "create", return_value=cloned)

    assert clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=7) is cloned

    dedup_source = owner if expected_uses_owner else source
    policy.deduplication_status.assert_called_once_with(dedup_source)
    dedup_snapshot.assert_called_once_with(policy.deduplication_status.return_value)
    source.save.assert_called_once_with(update_fields=["status", "is_dedup_settings_locked"])
    assert source.status == Rdp.PushStatus.REJECTED
    assert source.is_dedup_settings_locked is False
    create.assert_called_once_with(
        country_office_id=10,
        program_id=20,
        pushed_by_id=7,
        name="Clone",
        parent=owner,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id=expected_set_id,
        is_dedup_settings_locked=False,
    )
    snapshot.assert_called_once_with(
        rdp=source,
        key="before_clone",
        snapshot={"state": "Deduplicated"},
    )


def test_clone_rdp_core_integrity_error(
    mocker: MockerFixture,
    mock_dedup_status,
    mock_clone_flow,
    err_contains,
) -> None:
    source = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        country_office_id=10,
        program_id=20,
        deduplication_set_id="ds-1",
        is_dedup_settings_locked=False,
    )

    policy = mock_dedup_status()
    mock_clone_flow(source)
    snapshot = mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")
    snapshot_builder = mocker.patch(f"{MOD}._deduplication_snapshot", return_value={})
    mocker.patch.object(Rdp.objects, "create", side_effect=IntegrityError("boom"))

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=7)

    assert err_contains(exc.value.args[0]["errors"], "can not clone record")
    assert err_contains(exc.value.args[0]["errors"], "boom")
    snapshot_builder.assert_called_once_with(policy.deduplication_status.return_value)
    snapshot.assert_called_once_with(rdp=source, key="before_clone", snapshot={})


def test_reject_deduplication_set_existing_rdp_core(
    mocker: MockerFixture,
    mock_reject_flow,
) -> None:
    job, _, locked, client, require = mock_reject_flow()
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    snapshot = mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")

    assert reject_deduplication_set_existing_rdp_core(job) == {
        "rdp_id": 1,
        "program": "program-1",
        "deduplication_set_id": "ds-1",
        "rejected": True,
    }

    require.assert_called_once()
    client.reject.assert_called_once_with()
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.REJECTED,
        hope_rdi_id="",
        is_dedup_settings_locked=False,
    )
    snapshot.assert_called_once_with(
        rdp=locked,
        key="before_reject",
        snapshot={"state": "Deduplicated"},
    )


@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_reject_deduplication_set_existing_rdp_core_remote_error(
    mocker: MockerFixture,
    mock_reject_flow,
    exc_cls: type[Exception],
    err_contains,
) -> None:
    job, _, locked, client, require = mock_reject_flow(reject_error=exc_cls("boom"))
    snapshot = mocker.patch(f"{MOD}.set_rdp_deduplication_snapshot")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    with pytest.raises(HopePushError) as exc:
        reject_deduplication_set_existing_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "boom")
    require.assert_called_once()
    client.reject.assert_called_once_with()
    snapshot.assert_called_once_with(
        rdp=locked,
        key="before_reject",
        snapshot={"state": "Deduplicated"},
    )
    set_status.assert_not_called()


@pytest.mark.django_db
def test_mark_rdp_beneficiaries_removed(job: AsyncJob, beneficiary_instance: Beneficiary) -> None:
    _mark_rdp_beneficiaries_removed(job.rdp, job.program.beneficiary_group.master_detail)

    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.removed is True
    if isinstance(beneficiary_instance, CountryHousehold):
        assert all(member.removed for member in beneficiary_instance.members.all())


def test_mark_rdp_beneficiaries_removed_empty_master_detail(mocker: MockerFixture) -> None:
    owner = mocker.MagicMock()
    owner.households.values_list.return_value = []
    qs_inds = mocker.patch(f"{MOD}.qs_individuals_by_household_pks")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)

    _mark_rdp_beneficiaries_removed(mocker.MagicMock(), True)

    owner.households.update.assert_not_called()
    qs_inds.assert_not_called()


@pytest.mark.parametrize(
    ("hh_ids", "has_households"),
    [
        ([1, 2], True),
        ([], False),
    ],
    ids=["households", "individuals"],
)
def test_restore_rdp_removed_beneficiaries(
    mocker: MockerFixture,
    hh_ids: list[int],
    has_households: bool,
) -> None:
    owner = mocker.MagicMock()
    owner.households.values_list.return_value = hh_ids
    qs_inds = mocker.patch(f"{MOD}.qs_individuals_by_household_pks")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)

    _restore_rdp_removed_beneficiaries(mocker.MagicMock())

    if has_households:
        owner.households.update.assert_called_once_with(removed=False)
        qs_inds.assert_called_once_with(hh_ids)
        qs_inds.return_value.update.assert_called_once_with(removed=False)
        owner.individuals.update.assert_not_called()
        return

    owner.households.update.assert_not_called()
    qs_inds.assert_not_called()
    owner.individuals.update.assert_called_once_with(removed=False)


@pytest.mark.parametrize("master_detail", [True, False], ids=["master_detail", "flat"])
def test_steps(master_detail: bool, mocker: MockerFixture, proc: object) -> None:
    config = {"pks": [1, 2], "master_detail": master_detail}
    qs_by_hh = mocker.patch(f"{MOD}.qs_individuals_by_household_pks", return_value="ind_qs")
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
    locked = mocker.MagicMock()
    config = {"master_detail": True, "pks": [1], "rdp_id": 1}
    processor = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id="RID-1")
    step1 = mocker.Mock()
    step2 = mocker.Mock()
    job = mocker.MagicMock(config={"rdp_id": 1})
    job.owner.email = owner_email

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    require = mocker.patch(f"{MOD}._require_policy_check")
    save_snapshot = mocker.patch(f"{MOD}._save_current_deduplication_snapshot")
    workflow = mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    processor_cls = mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    steps_spy = mocker.patch(f"{MOD}._steps", return_value=[step1, step2])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    mark_removed = mocker.patch(f"{MOD}._mark_rdp_beneficiaries_removed")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    make_client = mocker.patch(f"{MOD}.make_dedup_client")

    assert push_existing_rdp_core(job) == {"errors": []}

    require.assert_called_once()
    save_snapshot.assert_called_once_with(rdp=rdp, key="before_push")
    workflow.assert_called_once_with(rdp=rdp, imported_by_email=expected_email)
    processor_cls.assert_called_once_with(config)
    steps_spy.assert_called_once_with(processor, config)
    step1.assert_called_once_with()
    step2.assert_called_once_with()
    mark_removed.assert_called_once_with(locked, True)
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.PUSHED,
        hope_rdi_id="RID-1",
    )
    make_client.assert_not_called()


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
    mocker.patch(f"{MOD}._require_policy_check")
    save_snapshot = mocker.patch(f"{MOD}._save_current_deduplication_snapshot")
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    next_step = mocker.Mock()
    mocker.patch(f"{MOD}._steps", return_value=[fail_step, next_step])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    mark_removed = mocker.patch(f"{MOD}._mark_rdp_beneficiaries_removed")

    with pytest.raises(HopePushError) as exc:
        push_existing_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "boom")
    save_snapshot.assert_called_once_with(rdp=rdp, key="before_push")
    mark_removed.assert_not_called()
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.FAILURE,
        hope_rdi_id=None,
    )
    next_step.assert_not_called()


@pytest.mark.parametrize(
    "hope_rdi_id",
    ["", "   ", None],
    ids=["empty", "blank", "none"],
)
def test_push_existing_rdp_core_requires_rdi_id_after_successful_steps(
    mocker: MockerFixture,
    err_contains,
    hope_rdi_id: str | None,
) -> None:
    rdp = mocker.MagicMock(pk=1)
    rdp.pushed_by.email = "pushed@example.com"
    config = {"master_detail": True, "pks": [1], "rdp_id": 1}
    processor = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id=hope_rdi_id)
    job = mocker.MagicMock(config={"rdp_id": 1})
    job.owner.email = ""

    mocker.patch(f"{MOD}.rdp_for_push", return_value=rdp)
    mocker.patch(f"{MOD}._require_policy_check")
    mocker.patch(f"{MOD}._save_current_deduplication_snapshot")
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    step = mocker.Mock()
    mocker.patch(f"{MOD}._steps", return_value=[step])
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update")
    mark_removed = mocker.patch(f"{MOD}._mark_rdp_beneficiaries_removed")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    with pytest.raises(HopePushError) as exc:
        push_existing_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "RDI id is not set")
    step.assert_called_once_with()
    lock.assert_not_called()
    mark_removed.assert_not_called()
    set_status.assert_not_called()


def test_reset_rdp_core_uses_rejected_callback_flow(
    mocker: MockerFixture,
    dedup_api_cm,
) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PUSHED,
        hope_rdi_id="RID-1",
        deduplication_set_id=uuid4(),
    )
    rdp.program.unicef_id = "program-1"
    client = mocker.MagicMock()
    job = mocker.MagicMock(config={"rdp_id": 1})

    def update_status(*, rdp: Rdp, status: Rdp.PushStatus, **_: object) -> None:
        rdp.status = status

    lock = mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    restore = mocker.patch(f"{MOD}._restore_rdp_removed_beneficiaries")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status", side_effect=update_status)

    payload = reset_rdp_core(job)

    assert payload["rdp_id"] == 1
    assert payload["rdi_id"] == "RID-1"
    assert payload["status"] == Rdp.PushStatus.REJECTED
    assert payload["code"] == HopeRdiCallbackCode.FINALIZED
    lock.assert_called_once_with(pk=1)
    client.reject.assert_called_once_with()
    restore.assert_called_once_with(rdp)
    set_status.assert_called_once_with(
        rdp=rdp,
        status=Rdp.PushStatus.REJECTED,
        hope_rdi_id="RID-1",
        is_dedup_settings_locked=False,
    )


def test_reset_rdp_core_requires_hope_rdi_id(
    mocker: MockerFixture,
    err_contains,
) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PUSHED,
        hope_rdi_id="",
        deduplication_set_id=None,
    )
    job = mocker.MagicMock(config={"rdp_id": 1})

    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)

    with pytest.raises(HopePushError) as exc:
        reset_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "RDI id is required")


def test_reset_rdp_core_wraps_missing_rdp(
    mocker: MockerFixture,
    err_contains,
) -> None:
    job = mocker.MagicMock(config={"rdp_id": 1})
    lock = mocker.patch(f"{MOD}.lock_rdp_for_update", side_effect=Rdp.DoesNotExist)

    with pytest.raises(HopePushError) as exc:
        reset_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "RDP not found")
    lock.assert_called_once_with(pk=1)


@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_reset_rdp_core_wraps_callback_errors(
    mocker: MockerFixture,
    dedup_api_cm,
    exc_cls: type[Exception],
    err_contains,
) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PUSHED,
        hope_rdi_id="RID-1",
        deduplication_set_id=uuid4(),
    )
    rdp.program.unicef_id = "program-1"
    client = mocker.MagicMock()
    client.reject.side_effect = exc_cls("boom")
    job = mocker.MagicMock(config={"rdp_id": 1})

    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=rdp)
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    restore = mocker.patch(f"{MOD}._restore_rdp_removed_beneficiaries")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    with pytest.raises(HopePushError) as exc:
        reset_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "final status sync failed")
    client.reject.assert_called_once_with()
    restore.assert_not_called()
    set_status.assert_not_called()


def test_apply_hope_rdi_final_status_rejects_empty_rdi_id(mocker: MockerFixture) -> None:
    lock = mocker.patch(f"{MOD}.lock_rdp_for_hope_callback")

    with pytest.raises(HopeRdiCallbackError) as exc:
        apply_hope_rdi_final_status(hope_rdi_id="", status=Rdp.PushStatus.MERGED)

    payload = exc.value.args[0]
    assert payload.code == HopeRdiCallbackCode.MISSING_RDI_ID
    assert payload.detail == "RDI id is required."
    lock.assert_not_called()


def test_apply_hope_rdi_final_status_wraps_missing_rdp(mocker: MockerFixture) -> None:
    lock = mocker.patch(f"{MOD}.lock_rdp_for_hope_callback", side_effect=Rdp.DoesNotExist)

    with pytest.raises(HopeRdiCallbackNotFoundError) as exc:
        apply_hope_rdi_final_status(hope_rdi_id="RID-404", status=Rdp.PushStatus.MERGED)

    payload = exc.value.args[0]
    assert payload.code == HopeRdiCallbackCode.NOT_FOUND
    assert payload.rdi_id == "RID-404"
    assert payload.detail == "RDP not found for RDI id."
    lock.assert_called_once_with(hope_rdi_id="RID-404")


@pytest.mark.parametrize(
    "status",
    [Rdp.PushStatus.MERGED, Rdp.PushStatus.REJECTED],
    ids=["merged", "rejected"],
)
def test_apply_hope_rdi_final_status_returns_already_finalized(
    mocker: MockerFixture,
    status: Rdp.PushStatus,
) -> None:
    rdp = mocker.MagicMock(pk=1, status=status, hope_rdi_id="RID-1")
    lock = mocker.patch(f"{MOD}.lock_rdp_for_hope_callback", return_value=rdp)
    finalize = mocker.patch(f"{MOD}._finalize_deduplication_set_for_hope_callback")
    restore = mocker.patch(f"{MOD}._restore_rdp_removed_beneficiaries")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    payload = apply_hope_rdi_final_status(hope_rdi_id="RID-1", status=status)

    assert payload.code == HopeRdiCallbackCode.ALREADY_FINALIZED
    assert payload.status == status
    lock.assert_called_once_with(hope_rdi_id="RID-1")
    finalize.assert_not_called()
    restore.assert_not_called()
    set_status.assert_not_called()


def test_apply_hope_rdi_final_status_rejects_invalid_transition(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock(pk=1, status=Rdp.PushStatus.FAILURE, hope_rdi_id="RID-1")
    lock = mocker.patch(f"{MOD}.lock_rdp_for_hope_callback", return_value=rdp)
    finalize = mocker.patch(f"{MOD}._finalize_deduplication_set_for_hope_callback")
    restore = mocker.patch(f"{MOD}._restore_rdp_removed_beneficiaries")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    with pytest.raises(HopeRdiCallbackConflictError) as exc:
        apply_hope_rdi_final_status(hope_rdi_id="RID-1", status=Rdp.PushStatus.MERGED)

    payload = exc.value.args[0]
    assert payload.code == HopeRdiCallbackCode.INVALID_TRANSITION
    assert payload.status == Rdp.PushStatus.FAILURE
    assert "status=FAILURE" in payload.detail
    lock.assert_called_once_with(hope_rdi_id="RID-1")
    finalize.assert_not_called()
    restore.assert_not_called()
    set_status.assert_not_called()


@pytest.mark.parametrize(
    ("status", "expected_action", "restores_beneficiaries", "expected_lock"),
    [
        (Rdp.PushStatus.MERGED, "approve", False, None),
        (Rdp.PushStatus.REJECTED, "reject", True, False),
    ],
    ids=["merged", "rejected"],
)
def test_apply_hope_rdi_final_status_syncs_dedup_engine(
    mocker: MockerFixture,
    dedup_api_cm,
    status: Rdp.PushStatus,
    expected_action: str,
    restores_beneficiaries: bool,
    expected_lock: bool | None,
) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PUSHED,
        hope_rdi_id="RID-1",
        deduplication_set_id=uuid4(),
    )
    rdp.program.unicef_id = "program-1"
    client = mocker.MagicMock()

    def update_status(*, rdp: Rdp, status: Rdp.PushStatus, **_: object) -> None:
        rdp.status = status

    lock = mocker.patch(f"{MOD}.lock_rdp_for_hope_callback", return_value=rdp)
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    restore = mocker.patch(f"{MOD}._restore_rdp_removed_beneficiaries")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status", side_effect=update_status)

    payload = apply_hope_rdi_final_status(hope_rdi_id="RID-1", status=status)

    assert payload.code == HopeRdiCallbackCode.FINALIZED
    assert payload.status == status
    lock.assert_called_once_with(hope_rdi_id="RID-1")
    getattr(client, expected_action).assert_called_once_with()
    if restores_beneficiaries:
        restore.assert_called_once_with(rdp)
    else:
        restore.assert_not_called()
    set_status.assert_called_once_with(
        rdp=rdp,
        status=status,
        hope_rdi_id="RID-1",
        is_dedup_settings_locked=expected_lock,
    )


@pytest.mark.parametrize(
    "exc_cls",
    [RemoteError, RemoteUnavailableError],
    ids=["remote_error", "remote_unavailable"],
)
def test_apply_hope_rdi_final_status_wraps_dedup_remote_errors(
    mocker: MockerFixture,
    dedup_api_cm,
    exc_cls: type[Exception],
) -> None:
    rdp = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PUSHED,
        hope_rdi_id="RID-1",
        deduplication_set_id=uuid4(),
    )
    rdp.program.unicef_id = "program-1"
    client = mocker.MagicMock()
    client.approve.side_effect = exc_cls("boom")

    lock = mocker.patch(f"{MOD}.lock_rdp_for_hope_callback", return_value=rdp)
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    restore = mocker.patch(f"{MOD}._restore_rdp_removed_beneficiaries")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    with pytest.raises(HopeRdiCallbackError) as exc:
        apply_hope_rdi_final_status(
            hope_rdi_id="RID-1",
            status=Rdp.PushStatus.MERGED,
        )

    assert "final status sync failed" in exc.value.args[0].detail
    lock.assert_called_once_with(hope_rdi_id="RID-1")
    client.approve.assert_called_once_with()
    restore.assert_not_called()
    set_status.assert_not_called()
