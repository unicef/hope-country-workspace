import pytest
from pytest_mock import MockerFixture
from collections.abc import Callable
from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.models import Rdp, AsyncJob
from country_workspace.workspaces.models import (
    CountryHousehold,
    CountryIndividual,
)
from country_workspace.contrib.hope.push.config import Beneficiary
from country_workspace.contrib.hope.push.orchestration import (
    push_to_hope_core,
    create_rdp_records,
    complete_rdp,
    mark_rdp_beneficiaries_removed,
    steps,
)

from functools import partial


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


# create_rdp_records: creates RDP, links beneficiaries, updates AsyncJob.rdp_id
@pytest.mark.django_db
def test_create_rdp_records_updates_async_job(push_config_base: dict, job: AsyncJob) -> None:
    rdp_id = create_rdp_records(push_config_base, job.id)
    job.refresh_from_db()
    assert job.rdp_id == rdp_id
    assert Rdp.objects.get(id=rdp_id).status == Rdp.PushStatus.PENDING


# complete_rdp: atomic update of status + hope_rdi_id
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


# mark_rdp_beneficiaries_removed: HH+members for MD; only IND for non-MD
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


@pytest.mark.django_db
def test_push_to_hope_core_success(mocker: MockerFixture, job):
    # Ensure non-empty PKs (we stub internals, no real DB writes)
    job.config["pks"] = [1, 2]

    mod = "country_workspace.contrib.hope.push.orchestration"
    hope_rdi_id = "test-rdi-123"
    proc = mocker.MagicMock(total={"errors": []}, hope_rdi_id=None)

    mocker.patch(f"{mod}.PushProcessor", return_value=proc)
    mocker.patch(f"{mod}.create_rdp_records", return_value=999)
    mock_complete = mocker.patch(f"{mod}.complete_rdp")
    mock_mark = mocker.patch(f"{mod}.mark_rdp_beneficiaries_removed")
    mocker.patch(
        f"{mod}.steps",
        side_effect=lambda p, cfg: iter((lambda: setattr(p, "hope_rdi_id", hope_rdi_id),)),
    )

    result = push_to_hope_core(job)

    assert result == {"errors": []}
    mock_complete.assert_called_once_with(999, Rdp.PushStatus.SUCCESS, hope_rdi_id)
    mock_mark.assert_called_once()


@pytest.mark.django_db
def test_push_to_hope_core_failure(mocker: MockerFixture, job):
    # Non-empty PKs to bypass guards
    job.config["pks"] = [1]

    mod = "country_workspace.contrib.hope.push.orchestration"
    hope_rdi_id = "test-rdi-123"
    proc = mocker.MagicMock(total={"errors": []}, hope_rdi_id=hope_rdi_id)

    mocker.patch(f"{mod}.PushProcessor", return_value=proc)
    mocker.patch(f"{mod}.create_rdp_records", return_value=321)
    mock_complete = mocker.patch(f"{mod}.complete_rdp")
    mocker.patch(f"{mod}.mark_rdp_beneficiaries_removed")
    mocker.patch(
        f"{mod}.steps",
        side_effect=lambda p, cfg: iter((lambda: p.total["errors"].append("boom"),)),
    )

    with pytest.raises(HopePushError):
        push_to_hope_core(job)

    mock_complete.assert_called_once_with(321, Rdp.PushStatus.FAILURE, hope_rdi_id)


@pytest.mark.django_db
def test_push_to_hope_core_no_beneficiary_group(job: AsyncJob, err_contains: Callable[[list[str], str], bool]) -> None:
    job.program.beneficiary_group = None
    out = push_to_hope_core(job)
    assert err_contains(out.get("errors", []), "beneficiary_group is not set")


@pytest.mark.django_db
def test_push_to_hope_core_no_pks(job: AsyncJob, err_contains: Callable[[list[str], str], bool]) -> None:
    job.config["pks"] = []
    out = push_to_hope_core(job)
    assert err_contains(out.get("errors", []), "no beneficiaries")


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
