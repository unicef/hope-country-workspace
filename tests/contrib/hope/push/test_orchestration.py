from collections.abc import Callable
from types import SimpleNamespace
import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.response import Status as DedupResponseStatus
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.push.config import Beneficiary
from country_workspace.contrib.hope.push.orchestration import (
    create_rdp_core,
    create_rdp_records,
    dedup_existing_rdp_core,
    mark_rdp_beneficiaries_removed,
    push_existing_rdp_core,
    reject_deduplication_set_existing_rdp_core,
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
            self.calls.append(("run_with", qs, step))

    return Proc()


@pytest.mark.django_db
def test_create_rdp_records_updates_async_job(create_config_base: dict, create_job: AsyncJob) -> None:
    rdp = create_rdp_records(create_config_base, create_job.id)
    create_job.refresh_from_db()
    assert (create_job.rdp_id, rdp.status) == (rdp.id, Rdp.PushStatus.PENDING)


@pytest.mark.django_db
def test_create_rdp_records_integrity_error(job: AsyncJob, push_config_base: dict, err_contains) -> None:
    with pytest.raises(HopePushError) as exc:
        create_rdp_records(push_config_base, job.id)
    assert err_contains(exc.value.args[0]["errors"], "RDP: can not create record")


@pytest.mark.django_db
def test_mark_rdp_beneficiaries_removed(job: AsyncJob, beneficiary_instance: Beneficiary) -> None:
    mark_rdp_beneficiaries_removed(job.rdp, job.program.beneficiary_group.master_detail)
    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.removed is True
    if isinstance(beneficiary_instance, CountryHousehold):
        assert all(member.removed for member in beneficiary_instance.members.all())


@pytest.mark.parametrize(
    ("beneficiary_group", "pks", "expected"),
    [
        (None, [1], "RDP: beneficiary_group is not set"),
        (object(), [], "RDP: no beneficiaries selected"),
    ],
    ids=["missing_group", "missing_pks"],
)
def test_create_rdp_core_guard_errors(
    mocker: MockerFixture,
    beneficiary_group: object | None,
    pks: list[int],
    expected: str,
) -> None:
    job = mocker.MagicMock(
        program=mocker.MagicMock(beneficiary_group=beneficiary_group, biometric_deduplication_enabled=False),
        config={"pks": pks, "master_detail": True},
    )

    with pytest.raises(HopePushError, match=expected):
        create_rdp_core(job)


@pytest.mark.django_db
def test_create_rdp_core_preflight_errors(mocker: MockerFixture, create_job: AsyncJob) -> None:
    mocker.patch(f"{MOD}.preflight_errors", return_value=["boom"])
    create = mocker.patch(f"{MOD}.create_rdp_records")

    with pytest.raises(HopePushError, match="boom"):
        create_rdp_core(create_job)

    create.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "error"),
    [
        (DedupResponseStatus.DS_NOT_EXPOSED, None),
        (
            DedupResponseStatus.PENDING,
            "DedupEngine: there is an existing non-inactive deduplication set for this program.",
        ),
    ],
    ids=["not_exposed", "active_set"],
)
def test_create_rdp_core_dedup_guard(
    mocker: MockerFixture,
    create_job: AsyncJob,
    dedup_api_cm,
    status: DedupResponseStatus,
    error: str | None,
) -> None:
    create_job.program.biometric_deduplication_enabled = True
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    create = mocker.patch(f"{MOD}.create_rdp_records", return_value=mocker.MagicMock(id=123, __str__=lambda _: "rdp"))

    client = mocker.MagicMock()
    client.status.return_value = SimpleNamespace(status=status)
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    if error:
        with pytest.raises(HopePushError, match=error):
            create_rdp_core(create_job)
        create.assert_not_called()
    else:
        assert create_rdp_core(create_job) == {"rdp_id": 123, "rdp_str": "rdp"}


@pytest.mark.django_db
def test_create_rdp_core_dedup_remote_error(
    mocker: MockerFixture,
    create_job: AsyncJob,
    dedup_api_cm,
) -> None:
    create_job.program.biometric_deduplication_enabled = True
    client = mocker.MagicMock()
    client.status.side_effect = RemoteError("boom")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    with pytest.raises(HopePushError, match="boom"):
        create_rdp_core(create_job)


@pytest.mark.django_db
def test_create_rdp_core_success(mocker: MockerFixture, create_job: AsyncJob) -> None:
    mocker.patch(f"{MOD}.preflight_errors", return_value=[])
    out = create_rdp_core(create_job)
    create_job.refresh_from_db()
    assert out == {"rdp_id": create_job.rdp_id, "rdp_str": str(create_job.rdp)}


@pytest.mark.parametrize("has_errors", [False, True], ids=["success", "failure"])
def test_dedup_existing_rdp_core(mocker: MockerFixture, has_errors: bool) -> None:
    total = {"errors": ["boom"]} if has_errors else {"errors": []}
    proc = mocker.MagicMock(total=total, has_errors=has_errors)
    mocker.patch(f"{MOD}.DedupProcessor", return_value=proc)

    if has_errors:
        with pytest.raises(HopePushError, match="boom"):
            dedup_existing_rdp_core(mocker.MagicMock(config={"rdp_id": 123}))
    else:
        assert dedup_existing_rdp_core(mocker.MagicMock(config={"rdp_id": 123})) == total

    proc.run.assert_called_once_with()


@pytest.mark.parametrize(
    ("enabled", "set_id", "expected"),
    [
        (False, "ds-1", "DedupEngine: biometric deduplication is not enabled for this program."),
        (True, "", "DedupEngine: deduplication_set_id is not set for this RDP."),
    ],
    ids=["disabled", "missing_set_id"],
)
def test_reject_deduplication_set_existing_rdp_core_guard_errors(
    mocker: MockerFixture,
    enabled: bool,
    set_id: str,
    expected: str,
) -> None:
    rdp = mocker.MagicMock(pk=1, deduplication_set_id=set_id)
    rdp.program.biometric_deduplication_enabled = enabled
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    with pytest.raises(HopePushError, match=expected):
        reject_deduplication_set_existing_rdp_core(mocker.MagicMock(config={"rdp_id": 1}))


@pytest.mark.parametrize(
    ("status", "rejected"),
    [
        (DedupResponseStatus.DS_NOT_EXPOSED, False),
        (DedupResponseStatus.PENDING, True),
    ],
    ids=["already_not_exposed", "reject_active_set"],
)
def test_reject_deduplication_set_existing_rdp_core(
    mocker: MockerFixture,
    dedup_api_cm,
    status: DedupResponseStatus,
    rejected: bool,
) -> None:
    rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1")
    rdp.program.biometric_deduplication_enabled = True
    rdp.program.unicef_id = "program-1"
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    client = mocker.MagicMock()
    client.status.return_value = SimpleNamespace(status=status)
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    assert reject_deduplication_set_existing_rdp_core(mocker.MagicMock(config={"rdp_id": 1})) == {
        "rdp_id": 1,
        "program": "program-1",
        "deduplication_set_id": "ds-1",
        "status": DedupResponseStatus.DS_NOT_EXPOSED.value if rejected else status.value,
        "rejected": rejected,
    }
    client.reject.assert_called_once_with() if rejected else client.reject.assert_not_called()


def test_reject_deduplication_set_existing_rdp_core_remote_error(
    mocker: MockerFixture,
    dedup_api_cm,
) -> None:
    rdp = mocker.MagicMock(pk=1, deduplication_set_id="ds-1")
    rdp.program.biometric_deduplication_enabled = True
    rdp.program.unicef_id = "program-1"
    mocker.patch(f"{MOD}.rdp_for_dedup", return_value=rdp)

    client = mocker.MagicMock()
    client.status.side_effect = RemoteError("boom")
    mocker.patch(f"{MOD}.make_dedup_client", return_value=dedup_api_cm(client))

    with pytest.raises(HopePushError, match="boom"):
        reject_deduplication_set_existing_rdp_core(mocker.MagicMock(config={"rdp_id": 1}))


@pytest.mark.parametrize(
    ("owner_email", "biometric", "step_error"),
    [
        ("owner@example.com", False, None),
        ("owner@example.com", True, None),
        ("", False, "boom"),
        ("", True, "boom"),
    ],
    ids=["success", "success_with_dedup", "failure", "failure_with_dedup"],
)
def test_push_existing_rdp_core(
    mocker: MockerFixture,
    job: AsyncJob,
    owner_email: str,
    biometric: bool,
    step_error: str | None,
) -> None:
    job.owner.email = owner_email
    locked = mocker.MagicMock(pk=job.rdp.pk)
    locked.program.biometric_deduplication_enabled = biometric
    proc = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id="rdi-1")

    def fail() -> None:
        proc.total = {"errors": [step_error]}
        proc.has_errors = True

    mocker.patch(f"{MOD}.rdp_for_push", return_value=job.rdp)
    mocker.patch(f"{MOD}.workflow_config_for_rdp", return_value={"master_detail": True, "pks": [1]})
    mocker.patch(f"{MOD}.PushProcessor", return_value=proc)
    mocker.patch(f"{MOD}.steps", return_value=iter((fail if step_error else (lambda: None),)))
    mocker.patch(f"{MOD}.lock_rdp_for_update", return_value=locked)
    mark = mocker.patch(f"{MOD}.mark_rdp_beneficiaries_removed")
    set_dedup = mocker.patch(f"{MOD}.set_rdp_dedup_state")
    set_status = mocker.patch(f"{MOD}.set_rdp_push_status")

    if step_error:
        with pytest.raises(HopePushError, match=step_error):
            push_existing_rdp_core(job)
        set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.FAILURE, hope_rdi_id="rdi-1")
        mark.assert_not_called()
        set_dedup.assert_not_called()
    else:
        assert push_existing_rdp_core(job) == proc.total
        mark.assert_called_once_with(locked, True)
        set_status.assert_called_once_with(rdp=locked, status=Rdp.PushStatus.SUCCESS, hope_rdi_id="rdi-1")
        set_dedup.assert_called_once_with(
            rdp_id=locked.pk, state=Rdp.DedupRunState.FINISHED
        ) if biometric else set_dedup.assert_not_called()


@pytest.mark.parametrize("master_detail", [True, False], ids=["master_detail", "people_only"])
def test_steps(mocker: MockerFixture, proc: object, master_detail: bool) -> None:
    pks = [1, 2]
    config = {"pks": pks, "master_detail": master_detail}

    if master_detail:
        individuals_qs, households_qs = object(), object()
        individuals = mocker.patch(f"{MOD}.qs_individuals_by_household_pks", return_value=individuals_qs)
        households = mocker.patch(f"{MOD}.qs_households", return_value=households_qs)
        expected = [
            "pre",
            "create",
            ("run_with", individuals_qs, proc.rdi_push_individuals),
            ("run_with", households_qs, proc.rdi_push_households),
            "complete",
        ]
    else:
        individuals_qs = object()
        individuals = mocker.patch(f"{MOD}.qs_individuals_by_pks", return_value=individuals_qs)
        expected = [
            "pre",
            "create",
            ("run_with", individuals_qs, proc.rdi_push_people),
            "complete",
        ]

    for step in steps(proc, config):
        step()

    assert proc.calls == expected
    individuals.assert_called_once_with(pks)
    if master_detail:
        households.assert_called_once_with(pks=pks)
