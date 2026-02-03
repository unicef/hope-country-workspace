import pytest
from pytest_mock import MockerFixture
from collections.abc import Callable
from functools import partial

from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.dedup_engine.response import Status as DedupResponseStatus
from country_workspace.models import Rdp, AsyncJob
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual
from country_workspace.contrib.hope.push.config import Beneficiary
from country_workspace.contrib.hope.push.orchestration import (
    create_rdp_core,
    create_rdp_records,
    dedup_existing_rdp_core,
    push_existing_rdp_core,
    complete_rdp,
    mark_rdp_beneficiaries_removed,
    steps,
)


@pytest.fixture
def proc():
    class P:
        def __init__(self):
            self.calls = []

        def preflight(self):
            self.calls.append("pre")

        def rdi_create(self):
            self.calls.append("create")

        def rdi_complete(self):
            self.calls.append("complete")

        def rdi_push_individuals(self):
            self.calls.append("push_inds")

        def rdi_push_households(self):
            self.calls.append("push_hhs")

        def rdi_push_people(self):
            self.calls.append("push_people")

        def run_with(self, qs, step):
            self.calls.append(("run_with", qs, step))

    return P()


@pytest.mark.django_db
def test_create_rdp_records_updates_async_job(create_config_base: dict, create_job: AsyncJob) -> None:
    rdp = create_rdp_records(create_config_base, create_job.id)
    create_job.refresh_from_db()
    assert create_job.rdp_id == rdp.id
    assert Rdp.objects.get(id=rdp.id).status == Rdp.PushStatus.PENDING


@pytest.mark.django_db
def test_create_rdp_records_integrity_error(job, push_config_base, err_contains) -> None:
    with pytest.raises(HopePushError) as exc:
        create_rdp_records(push_config_base, job.id)
    assert err_contains(exc.value.args[0].get("errors", []), "RDP: can not create record")


@pytest.mark.django_db
@pytest.mark.parametrize("rdp_exists", [True, False], ids=["exists", "not_exists"])
def test_complete_rdp(job: AsyncJob, rdp_exists: bool) -> None:
    rdp_id = job.rdp.id if rdp_exists else 999_999
    hope_rdi_id = "test-rdi-123"

    if rdp_exists:
        r = complete_rdp(rdp_id, Rdp.PushStatus.SUCCESS, hope_rdi_id)
        assert (r.status, r.hope_rdi_id) == (Rdp.PushStatus.SUCCESS, hope_rdi_id)
    else:
        with pytest.raises(Rdp.DoesNotExist):
            complete_rdp(rdp_id, Rdp.PushStatus.SUCCESS, hope_rdi_id)


@pytest.mark.django_db
def test_mark_rdp_beneficiaries_removed(job: AsyncJob, beneficiary_instance: Beneficiary) -> None:
    md = job.program.beneficiary_group.master_detail
    mark_rdp_beneficiaries_removed(job.rdp, md)

    beneficiary_instance.refresh_from_db()
    assert beneficiary_instance.removed
    if md and isinstance(beneficiary_instance, CountryHousehold):
        for m in beneficiary_instance.members.all():
            m.refresh_from_db()
            assert m.removed
    if not md and isinstance(beneficiary_instance, CountryIndividual):
        assert beneficiary_instance.removed


def test_create_rdp_core_no_beneficiary_group(
    mocker: MockerFixture, err_contains: Callable[[list[str], str], bool]
) -> None:
    job = mocker.MagicMock(program=mocker.MagicMock(beneficiary_group=None), config={"pks": [1]})
    with pytest.raises(HopePushError) as exc:
        create_rdp_core(job)
    assert err_contains(exc.value.args[0].get("errors", []), "beneficiary_group is not set")


@pytest.mark.django_db
def test_create_rdp_core_no_pks(create_job: AsyncJob, err_contains: Callable[[list[str], str], bool]) -> None:
    create_job.config["pks"] = []
    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)
    assert err_contains(exc.value.args[0].get("errors", []), "no beneficiaries selected")


@pytest.mark.django_db
def test_create_rdp_core_preflight_errors(mocker: MockerFixture, create_job: AsyncJob) -> None:
    mod = "country_workspace.contrib.hope.push.orchestration"
    mocker.patch(f"{mod}.preflight_errors", return_value=["boom"])
    spy_create = mocker.patch(f"{mod}.create_rdp_records")

    with pytest.raises(HopePushError) as exc:
        create_rdp_core(create_job)

    assert exc.value.args[0]["errors"] == ["boom"]
    spy_create.assert_not_called()


@pytest.mark.django_db
def test_create_rdp_core_success(mocker: MockerFixture, create_job: AsyncJob) -> None:
    mod = "country_workspace.contrib.hope.push.orchestration"
    mocker.patch(f"{mod}.preflight_errors", return_value=[])

    out = create_rdp_core(create_job)

    create_job.refresh_from_db()
    assert out["rdp_id"] == create_job.rdp_id
    assert out["rdp_str"] == str(create_job.rdp)


def test_dedup_existing_rdp_core_success(mocker: MockerFixture) -> None:
    mod = "country_workspace.contrib.hope.push.orchestration"
    job = mocker.MagicMock(config={"rdp_id": 123})
    proc = mocker.MagicMock(total={"errors": []}, has_errors=False)

    mocker.patch(f"{mod}.DedupProcessor", return_value=proc)

    out = dedup_existing_rdp_core(job)

    proc.run.assert_called_once_with()
    assert out == {"errors": []}


def test_dedup_existing_rdp_core_failure(mocker: MockerFixture) -> None:
    mod = "country_workspace.contrib.hope.push.orchestration"
    job = mocker.MagicMock(config={"rdp_id": 123})
    proc = mocker.MagicMock(total={"errors": ["boom"]}, has_errors=True)

    mocker.patch(f"{mod}.DedupProcessor", return_value=proc)

    with pytest.raises(HopePushError) as exc:
        dedup_existing_rdp_core(job)

    assert exc.value.args[0] == {"errors": ["boom"]}


@pytest.mark.django_db
@pytest.mark.parametrize("is_duplicate", [False, True], ids=["no_deduplicate", "duplicate"])
def test_push_existing_rdp_core_success(mocker, job, is_duplicate):
    mod = "country_workspace.contrib.hope.push.orchestration"
    hope_rdi_id = "rdi-1"
    job.rdp.program.biometric_deduplication_enabled = is_duplicate
    job.rdp.program.__class__.objects.filter(pk=job.rdp.program_id).update(
        biometric_deduplication_enabled=is_duplicate,
        code="TEST" if is_duplicate else job.rdp.program.code,
    )

    if is_duplicate:
        job.rdp.program.code = "TEST"

        de = mocker.MagicMock()
        de.status.return_value = mocker.MagicMock(status=DedupResponseStatus.SUCCESS)
        de.approve.return_value = True

        mocker.patch(
            f"{mod}.dedup_api",
            return_value=mocker.MagicMock(
                __enter__=mocker.Mock(return_value=de), __exit__=mocker.Mock(return_value=False)
            ),
        )

    cfg = {
        "pks": [1],
        "master_detail": job.program.beneficiary_group.master_detail,
        "program_hope_id": "program-hope-id",
        "co_slug": "co",
        "batch_name": "Test Batch",
        "imported_by_email": "u@example.com",
    }
    mocker.patch(f"{mod}.workflow_config_for_rdp", return_value=cfg)

    proc = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id=hope_rdi_id)
    mocker.patch(f"{mod}.PushProcessor", return_value=proc)
    mocker.patch(f"{mod}.steps", return_value=iter((lambda: None,)))

    mock_complete = mocker.patch(f"{mod}.complete_rdp", return_value=job.rdp)
    mock_mark = mocker.patch(f"{mod}.mark_rdp_beneficiaries_removed")

    push_existing_rdp_core(job)

    mock_complete.assert_called_once_with(job.rdp.id, Rdp.PushStatus.SUCCESS, hope_rdi_id)
    mock_mark.assert_called_once()

    if is_duplicate:
        job.rdp.refresh_from_db()
        assert job.rdp.dedup_run_state == Rdp.DedupRunState.APPROVED


@pytest.mark.django_db
@pytest.mark.parametrize(
    "case",
    ["push_step_error", "dedup_status_none", "dedup_approve_false"],
    ids=["push_step_error", "dedup_status_none", "dedup_approve_false"],
)
def test_push_existing_rdp_core_failure(mocker: MockerFixture, job: AsyncJob, case: str) -> None:
    mod = "country_workspace.contrib.hope.push.orchestration"
    hope_rdi_id = "test-rdi-123"
    job.config["rdp_id"] = job.rdp.id

    deduplicate = case != "push_step_error"
    job.rdp.program.__class__.objects.filter(pk=job.rdp.program_id).update(
        biometric_deduplication_enabled=deduplicate,
        code="TEST" if deduplicate else job.rdp.program.code,
    )

    cfg = {
        "batch_name": "Test Batch",
        "co_slug": "co",
        "imported_by_email": "u@example.com",
        "program_hope_id": "program-hope-id",
        "master_detail": job.program.beneficiary_group.master_detail,
        "pks": [1],
    }
    mocker.patch(f"{mod}.workflow_config_for_rdp", return_value=cfg)

    proc = mocker.MagicMock(total={"errors": []}, has_errors=False, hope_rdi_id=hope_rdi_id)
    mocker.patch(f"{mod}.PushProcessor", return_value=proc)

    mock_complete = mocker.patch(f"{mod}.complete_rdp")
    mock_mark = mocker.patch(f"{mod}.mark_rdp_beneficiaries_removed")

    if case == "push_step_error":

        def _fail_step() -> None:
            proc.total["errors"].append("boom")
            proc.has_errors = True

        mocker.patch(f"{mod}.steps", return_value=iter((_fail_step,)))
    else:
        mocker.patch(f"{mod}.steps", return_value=iter((lambda: None,)))

        de = mocker.MagicMock()
        if case == "dedup_status_none":

            def _status() -> None:
                proc.total["errors"].append("DedupEngine: status() failed")

            de.status.side_effect = _status
        else:
            de.status.return_value = mocker.MagicMock(status=DedupResponseStatus.SUCCESS)

            def _approve() -> bool:
                proc.total["errors"].append("DedupEngine: approve() failed")
                return False

            de.approve.side_effect = _approve

        mocker.patch(
            f"{mod}.dedup_api",
            return_value=mocker.MagicMock(
                __enter__=mocker.Mock(return_value=de),
                __exit__=mocker.Mock(return_value=False),
            ),
        )

    with pytest.raises(HopePushError):
        push_existing_rdp_core(job)

    if case == "push_step_error":
        mock_complete.assert_called_once_with(job.rdp.id, Rdp.PushStatus.FAILURE, hope_rdi_id)
    else:
        mock_complete.assert_not_called()

    mock_mark.assert_not_called()


@pytest.mark.parametrize("master_detail", [True, False], ids=["md", "people_only"])
def test_steps_sequence_and_partials(mocker, proc, master_detail):
    pks = [1, 2]
    cfg = {"pks": pks, "master_detail": master_detail}
    mod = "country_workspace.contrib.hope.push.orchestration"

    if master_detail:
        inds_qs, hhs_qs = object(), object()
        spy_inds = mocker.patch(f"{mod}.individuals_by_household_pks", return_value=inds_qs)
        spy_hhs = mocker.patch(f"{mod}.households", return_value=hhs_qs)

        seq = list(steps(proc, cfg))
        assert [seq[0].__name__, seq[1].__name__, seq[-1].__name__] == ["preflight", "rdi_create", "rdi_complete"]
        assert isinstance(seq[2], partial)
        assert seq[2].func.__self__ is proc
        assert seq[2].args[0] is inds_qs
        assert seq[2].args[1].__name__ == "rdi_push_individuals"
        assert isinstance(seq[3], partial)
        assert seq[3].func.__self__ is proc
        assert seq[3].args[0] is hhs_qs
        assert seq[3].args[1].__name__ == "rdi_push_households"
        spy_inds.assert_called_once_with(pks)
        spy_hhs.assert_called_once_with(pks=pks)
    else:
        inds_qs = object()
        spy_inds = mocker.patch(f"{mod}.individuals_by_pks", return_value=inds_qs)

        seq = list(steps(proc, cfg))
        assert [seq[0].__name__, seq[1].__name__, seq[-1].__name__] == ["preflight", "rdi_create", "rdi_complete"]
        assert len(seq) == 4
        assert isinstance(seq[2], partial)
        assert seq[2].func.__self__ is proc
        assert seq[2].args[0] is inds_qs
        assert seq[2].args[1].__name__ == "rdi_push_people"
        spy_inds.assert_called_once_with(pks)

    for s in seq:
        s()
