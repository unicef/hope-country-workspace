from collections.abc import Callable

import pytest
from django.db import IntegrityError
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.push.config import Beneficiary
from country_workspace.contrib.hope.push.orchestration import (
    clone_rdp_core,
    create_rdp_core,
    dedup_existing_rdp_core,
    mark_rdp_beneficiaries_removed,
    push_existing_rdp_core,
    reject_deduplication_set_existing_rdp_core,
    require_rdp_action,
    steps,
)
from country_workspace.exceptions import RemoteError
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


def test_require_rdp_action_calls_policy_action(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock()
    check = mocker.MagicMock()
    policy = mocker.MagicMock()
    policy.can_push.return_value = check
    policy_cls = mocker.patch(f"{MOD}.RdpActionPolicy", return_value=policy)

    require_rdp_action(rdp, "can_push")

    policy_cls.assert_called_once_with(rdp)
    policy.can_push.assert_called_once_with()
    check.require.assert_called_once_with()


def test_require_rdp_action_wraps_remote_error(mocker: MockerFixture, err_contains) -> None:
    rdp = mocker.MagicMock()
    check = mocker.MagicMock()
    check.require.side_effect = RemoteError("boom")
    policy = mocker.MagicMock()
    policy.can_push.return_value = check
    mocker.patch(f"{MOD}.RdpActionPolicy", return_value=policy)

    with pytest.raises(HopePushError) as exc:
        require_rdp_action(rdp, "can_push")

    assert err_contains(exc.value.args[0]["errors"], "boom")


@pytest.mark.django_db
def test_mark_rdp_beneficiaries_removed(job: AsyncJob, beneficiary_instance: Beneficiary) -> None:
    mark_rdp_beneficiaries_removed(job.rdp, job.program.beneficiary_group.master_detail)

    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.removed is True
    if isinstance(beneficiary_instance, CountryHousehold):
        assert all(member.removed for member in beneficiary_instance.members.all())


def test_mark_rdp_beneficiaries_removed_empty_master_detail(mocker: MockerFixture) -> None:
    owner = mocker.MagicMock()
    owner.households.values_list.return_value = []
    qs_inds = mocker.patch(f"{MOD}.qs_individuals_by_household_pks")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)

    mark_rdp_beneficiaries_removed(mocker.MagicMock(), True)

    owner.households.update.assert_not_called()
    qs_inds.assert_not_called()


@pytest.mark.parametrize("master_detail", [True, False], ids=["master_detail", "flat"])
def test_steps(master_detail: bool, mocker: MockerFixture, proc: object) -> None:
    config = {"pks": [1, 2], "master_detail": master_detail}
    qs_by_hh = mocker.patch(f"{MOD}.qs_individuals_by_household_pks", return_value="ind_qs")
    qs_hh = mocker.patch(f"{MOD}.qs_households", return_value="hh_qs")
    qs_by_pks = mocker.patch(f"{MOD}.qs_individuals_by_pks", return_value="people_qs")

    for step in steps(proc, config):
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
def test_create_rdp_core_dedup_remote_error(
    mocker: MockerFixture,
    create_job: AsyncJob,
    dedup_api_cm,
    err_contains,
) -> None:
    create_job.program.biometric_deduplication_enabled = True
    client = mocker.MagicMock()
    client.can_create_deduplication_set.side_effect = RemoteError("boom")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "boom")


@pytest.mark.django_db
def test_create_rdp_core_preflight_errors(
    mocker: MockerFixture,
    create_job: AsyncJob,
    err_contains,
) -> None:
    create_job.program.biometric_deduplication_enabled = False
    mocker.patch(f"{MOD}.preflight_errors", return_value=["boom"])

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "boom")


@pytest.mark.django_db
def test_create_rdp_core_integrity_error(
    mocker: MockerFixture,
    create_job: AsyncJob,
    err_contains,
) -> None:
    create_job.program.biometric_deduplication_enabled = False
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch.object(Rdp.objects, "create", side_effect=IntegrityError("boom"))

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert err_contains(exc.value.args[0]["errors"], "can not create record")
    assert err_contains(exc.value.args[0]["errors"], "boom")


@pytest.mark.django_db
def test_create_rdp_core_success(mocker: MockerFixture, create_job: AsyncJob) -> None:
    create_job.program.biometric_deduplication_enabled = False
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])

    out = create_rdp_core(create_job)

    create_job.refresh_from_db()
    assert out == {"rdp_id": create_job.rdp_id, "rdp_str": str(create_job.rdp)}


def test_clone_rdp_core_preflight_errors(mocker: MockerFixture, err_contains) -> None:
    source = mocker.MagicMock()
    owner = mocker.MagicMock()

    mocker.patch(f"{MOD}.require_rdp_action")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", return_value=owner)
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=["boom"])

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=1)

    assert err_contains(exc.value.args[0]["errors"], "boom")


def test_clone_rdp_core_blocks_when_other_pending_exists(mocker: MockerFixture, err_contains) -> None:
    source = mocker.MagicMock(pk=1, status=Rdp.PushStatus.PENDING)
    owner = source

    mocker.patch(f"{MOD}.require_rdp_action")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", side_effect=[owner, owner])
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=source)
    mocker.patch(f"{MOD}.has_other_pending_rdp", return_value=True)

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=1)

    assert err_contains(exc.value.args[0]["errors"], "another RDP is pending")


def test_clone_rdp_core_integrity_error(mocker: MockerFixture, err_contains) -> None:
    source = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.SUCCESS,
        country_office_id=10,
        program_id=20,
        deduplication_set_id="ds-1",
    )
    owner = source

    mocker.patch(f"{MOD}.require_rdp_action")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", side_effect=[owner, owner])
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=source)
    mocker.patch(f"{MOD}.has_other_pending_rdp", return_value=False)
    mocker.patch.object(Rdp.objects, "create", side_effect=IntegrityError("boom"))

    with pytest.raises(HopePushError) as exc:
        clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=7)

    assert err_contains(exc.value.args[0]["errors"], "can not clone record")
    assert err_contains(exc.value.args[0]["errors"], "boom")


def test_clone_rdp_core_success_cancels_pending_source(mocker: MockerFixture) -> None:
    source = mocker.MagicMock(
        pk=1,
        status=Rdp.PushStatus.PENDING,
        country_office_id=10,
        program_id=20,
        deduplication_set_id="ds-1",
    )
    owner = source
    cloned = mocker.MagicMock()

    mocker.patch(f"{MOD}.require_rdp_action")
    mocker.patch(f"{MOD}.selection_owner_for_rdp", side_effect=[owner, owner])
    mocker.patch(f"{MOD}.rdp_selection", return_value=(True, [1, 2]))
    mocker.patch(f"{MOD}.preflight_exclude_rdp_ids", return_value=(1,))
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=source)
    mocker.patch(f"{MOD}.has_other_pending_rdp", return_value=False)
    create = mocker.patch.object(Rdp.objects, "create", return_value=cloned)

    assert clone_rdp_core(source=source, batch_name="Clone", pushed_by_id=7) is cloned

    source.save.assert_called_once_with(update_fields=["status"])
    create.assert_called_once_with(
        country_office_id=10,
        program_id=20,
        pushed_by_id=7,
        name="Clone",
        parent=owner,
        status=Rdp.PushStatus.PENDING,
        deduplication_set_id="ds-1",
        hope_rdi_id="",
    )


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
    require = mocker.patch(f"{MOD}.require_rdp_action")
    processor_cls = mocker.patch(f"{MOD}.DedupProcessor", return_value=processor)

    if has_errors:
        with pytest.raises(HopePushError) as exc:
            dedup_existing_rdp_core(job)
        assert err_contains(exc.value.args[0]["errors"], "boom")
    else:
        assert dedup_existing_rdp_core(job) == total

    require.assert_called_once_with(rdp, "can_deduplicate")
    processor_cls.assert_called_once_with(rdp)
    processor.run.assert_called_once_with()


def test_reject_deduplication_set_existing_rdp_core(
    mocker: MockerFixture,
    dedup_api_cm,
) -> None:
    rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1", hope_rdi_id="")
    rdp.program.unicef_id = "program-1"
    locked = mocker.MagicMock(hope_rdi_id="")
    job = mocker.MagicMock(config={"rdp_id": 1})

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    require = mocker.patch(f"{MOD}.require_rdp_action")
    client = mocker.MagicMock()
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    assert reject_deduplication_set_existing_rdp_core(job) == {
        "rdp_id": 1,
        "program": "program-1",
        "deduplication_set_id": "ds-1",
        "rejected": True,
    }

    require.assert_called_once_with(rdp, "can_reject_ds")
    client.reject.assert_called_once_with()
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.CANCELLED,
        hope_rdi_id="N/A",
    )


def test_reject_deduplication_set_existing_rdp_core_remote_error(
    mocker: MockerFixture,
    dedup_api_cm,
    err_contains,
) -> None:
    rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1")
    rdp.program.unicef_id = "program-1"
    job = mocker.MagicMock(config={"rdp_id": 1})

    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)
    mocker.patch(f"{MOD}.require_rdp_action")
    client = mocker.MagicMock()
    client.reject.side_effect = RemoteError("boom")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    with pytest.raises(HopePushError) as exc:
        reject_deduplication_set_existing_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "boom")


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
    require = mocker.patch(f"{MOD}.require_rdp_action")
    workflow = mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    processor_cls = mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    steps_spy = mocker.patch(f"{MOD}.steps", return_value=[step1, step2])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    mark_removed = mocker.patch(f"{MOD}.mark_rdp_beneficiaries_removed")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    assert push_existing_rdp_core(job) == {"errors": []}

    require.assert_called_once_with(rdp, "can_push")
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
    mocker.patch(f"{MOD}.require_rdp_action")
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value=config)
    mocker.patch(f"{MOD}.PushProcessor", return_value=processor)
    mocker.patch(f"{MOD}.steps", return_value=[fail_step])
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")
    mark_removed = mocker.patch(f"{MOD}.mark_rdp_beneficiaries_removed")

    with pytest.raises(HopePushError) as exc:
        push_existing_rdp_core(job)

    assert err_contains(exc.value.args[0]["errors"], "boom")
    mark_removed.assert_not_called()
    set_status.assert_called_once_with(
        rdp=locked,
        status=Rdp.PushStatus.FAILURE,
        hope_rdi_id="N/A",
    )
