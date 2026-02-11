import pytest
from pytest_mock import MockerFixture
import country_workspace.contrib.hope.push.repository as repo
from country_workspace.models import Rdp as RdpModel
from testutils.factories import (
    CountryProgramFactory,
    CountryRdpFactory,
    CountryHouseholdFactory,
    CountryIndividualFactory,
    DataSerializerFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db

# --------------------------- fixtures (factories) ---------------------------


@pytest.fixture
def program_no_serializer():
    return CountryProgramFactory(serializer=None)


@pytest.fixture
def program_with_serializer():
    return CountryProgramFactory(serializer=DataSerializerFactory())


@pytest.fixture
def rdp(program_with_serializer):
    return CountryRdpFactory(program=program_with_serializer)


@pytest.fixture
def rdp_qs(rdp):
    return RdpModel.objects.filter(pk=rdp.pk)


@pytest.fixture
def rdp_pair(program_with_serializer):
    """One PENDING and one SUCCESS RDP for filter/exclude test."""
    r1 = CountryRdpFactory(program=program_with_serializer, status=repo.Rdp.PushStatus.PENDING)
    r2 = CountryRdpFactory(program=program_with_serializer, status=repo.Rdp.PushStatus.SUCCESS)
    return r1, r2


@pytest.fixture
def hh_with_members():
    """Household with at least two members."""
    hh = CountryHouseholdFactory()
    if not hh.members.exists():
        CountryIndividualFactory.create_batch(2, household=hh)
    return hh


@pytest.fixture
def hh_all_members_with_rdp(hh_with_members, rdp):
    """Attach the same RDP to all members of the household."""
    for ind in hh_with_members.members.all():
        ind.rdp.add(rdp)
    return hh_with_members


@pytest.fixture
def two_hhs_with_rdp(rdp):
    """Two households, each linked to the same RDP."""
    h1 = CountryHouseholdFactory(rdps=rdp)
    h2 = CountryHouseholdFactory(rdps=rdp)
    return h1, h2


@pytest.fixture
def inds3():
    """Three individuals not linked to any HH by default."""
    return [CountryIndividualFactory(), CountryIndividualFactory(), CountryIndividualFactory()]


@pytest.fixture
def inds2_with_rdp(inds3, rdp):
    """Pick two individuals, attach RDP to both, and return them."""
    i1, i2 = inds3[0], inds3[1]
    i1.rdp.add(rdp)
    i2.rdp.add(rdp)
    return i1, i2


@pytest.fixture
def rdp_with_individual_links(program_with_serializer):
    rdp = CountryRdpFactory(program=program_with_serializer)
    i1 = CountryIndividualFactory()
    i2 = CountryIndividualFactory()
    i1.rdp.add(rdp)
    i2.rdp.add(rdp)
    return rdp, (i1, i2)


@pytest.fixture
def rdp_with_household_link(program_with_serializer):
    rdp = CountryRdpFactory(program=program_with_serializer)
    hh = CountryHouseholdFactory(rdps=rdp)
    if not hh.members.exists():
        CountryIndividualFactory.create_batch(2, household=hh)
    return rdp, hh


@pytest.fixture
def pushed_by_user():
    return UserFactory()


@pytest.fixture
def rdp_with_pushed_by(program_with_serializer, pushed_by_user):
    return CountryRdpFactory(program=program_with_serializer, pushed_by=pushed_by_user)


@pytest.fixture
def rdp_id():
    return 123


# --------------------------- serializer_for_program -------------------------


def test_serializer_for_program_identity_when_none(program_no_serializer):
    f = repo.serializer_for_program(program_no_serializer.hope_id)
    data = {"a": 1}
    assert f(data) == data  # identity when serializer is missing


def test_serializer_for_program_uses_serializer(program_with_serializer):
    f = repo.serializer_for_program(program_with_serializer.hope_id)
    data = {"x": 1}  # factory serializer returns data as-is in this setup
    assert f(data) == data


# --------------------------- rdp_pending_or_success -------------------------


def test_rdp_pending_or_success_filters_and_excludes(rdp_pair):
    r1, r2 = rdp_pair
    got = list(repo.rdp_pending_or_success(exclude_id=r1.id).values_list("id", flat=True))
    assert r2.id in got
    assert r1.id not in got


# --------------------------- individuals helpers ----------------------------


@pytest.mark.parametrize(
    ("builder", "arg_name", "expected_ids"),
    [
        # by household: all HH members ordered asc
        (
            repo.individuals_by_household_pks,
            "hh_pks",
            lambda hh, __: list(hh.members.order_by("id").values_list("id", flat=True)),
        ),
        # by explicit pks: only chosen individuals ordered asc
        (
            repo.individuals_by_pks,
            "pks",
            lambda __, inds: sorted([inds[0].id, inds[2].id]),
        ),
    ],
    ids=["by_hh", "by_pks"],
)
def test_individuals_filters_and_ordering(builder, arg_name, expected_ids, hh_with_members, inds3):
    if arg_name == "hh_pks":
        got = list(builder([hh_with_members.id]).values_list("id", flat=True))
    else:
        # choose i1 and i3
        got = list(builder([inds3[2].id, inds3[0].id]).values_list("id", flat=True))
    assert got == expected_ids(hh_with_members, inds3)


# --------------------------- households (prefetch members) ------------------


@pytest.mark.parametrize("prefetch_members", [True, False], ids=["prefetch", "noprefetch"])
def test_households_prefetch_members_toggle(hh_with_members, prefetch_members):
    qs = repo.households(pks=[hh_with_members.id], prefetch_members=prefetch_members)
    items = list(qs)
    if prefetch_members:
        assert all(hasattr(h, "prefetched_members") and h.prefetched_members for h in items)
    else:
        assert all(not hasattr(h, "prefetched_members") for h in items)


# --------------------------- preflight builders (Prefetch RDP) --------------


def test_individuals_for_preflight_by_pks_prefetches_rdp(inds2_with_rdp, rdp_qs, rdp):
    i1, i2 = inds2_with_rdp
    qs = repo.individuals_for_preflight_by_pks(pks=[i1.id, i2.id], rdp_qs=rdp_qs)
    rows = list(qs)
    assert rows
    assert all(hasattr(rw, "rdp_pre") and [x.pk for x in rw.rdp_pre] == [rdp.pk] for rw in rows)


def test_individuals_for_preflight_by_households_prefetches_rdp(hh_all_members_with_rdp, rdp_qs, rdp):
    qs = repo.individuals_for_preflight_by_households(hh_pks=[hh_all_members_with_rdp.id], rdp_qs=rdp_qs)
    rows = list(qs)
    assert rows
    assert all(hasattr(rw, "rdp_pre") and [x.pk for x in rw.rdp_pre] == [rdp.pk] for rw in rows)


def test_households_for_preflight_prefetches_rdp(two_hhs_with_rdp, rdp_qs, rdp):
    h1, h2 = two_hhs_with_rdp
    qs = repo.households_for_preflight(pks=[h1.id, h2.id], rdp_qs=rdp_qs)
    rows = list(qs)
    assert rows
    assert all(hasattr(h, "rdp_pre") and [x.pk for x in h.rdp_pre] == [rdp.pk] for h in rows)


# --------------------------- rdp_selection / individuals_for_rdp ------------


def test_rdp_selection_prefers_households(two_hhs_with_rdp):
    h1, h2 = two_hhs_with_rdp
    rdp = h1.rdp.first()
    master_detail, pks = repo.rdp_selection(rdp=rdp)
    assert master_detail is True
    assert set(pks) == {h1.pk, h2.pk}


def test_rdp_selection_falls_back_to_individuals(rdp_with_individual_links):
    rdp, (i1, i2) = rdp_with_individual_links
    master_detail, pks = repo.rdp_selection(rdp=rdp)
    assert master_detail is False
    assert set(pks) == {i1.pk, i2.pk}


@pytest.mark.parametrize(
    ("fixture_name", "builder"),
    [
        ("rdp_with_household_link", repo.individuals_by_household_pks),
        ("rdp_with_individual_links", repo.individuals_by_pks),
    ],
    ids=["by_households", "by_pks"],
)
def test_individuals_for_rdp_uses_selection(request: pytest.FixtureRequest, fixture_name, builder):
    rdp, selection = request.getfixturevalue(fixture_name)

    if builder is repo.individuals_by_household_pks:
        hh = selection
        expected = list(builder([hh.pk]).values_list("id", flat=True))
    else:
        i1, i2 = selection
        expected = list(builder([i1.pk, i2.pk]).values_list("id", flat=True))

    got = list(repo.individuals_for_rdp(rdp=rdp).values_list("id", flat=True))
    assert got == expected


# --------------------------- workflow_config_for_rdp ------------------------


@pytest.mark.parametrize(
    ("fixture_name", "master_detail"),
    [
        ("rdp_with_household_link", True),
        ("rdp_with_individual_links", False),
    ],
    ids=["master_detail", "people_only"],
)
def test_workflow_config_for_rdp_builds_expected(
    request: pytest.FixtureRequest, fixture_name: str, master_detail: bool
):
    rdp, selection = request.getfixturevalue(fixture_name)
    imported_by_email = "u@example.com"

    cfg = repo.workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email)

    assert cfg["batch_name"] == rdp.name
    assert cfg["co_slug"] == rdp.program.country_office.slug
    assert cfg["imported_by_email"] == imported_by_email
    assert cfg["master_detail"] is master_detail
    assert cfg["program_hope_id"] == rdp.program.hope_id
    assert cfg["rdp_id"] == rdp.pk

    if master_detail:
        expected_pks = [selection.pk]
    else:
        i1, i2 = selection
        expected_pks = [i1.pk, i2.pk]
    assert set(cfg["pks"]) == set(expected_pks)


# --------------------------- rdp_for_* loaders ------------------------------


def test_rdp_for_dedup_returns_rdp_with_program(rdp):
    obj = repo.rdp_for_dedup(pk=rdp.pk)
    assert obj.pk == rdp.pk
    assert obj.program.pk == rdp.program.pk


def test_rdp_for_push_returns_rdp_with_required_relations(rdp_with_pushed_by, pushed_by_user):
    obj = repo.rdp_for_push(pk=rdp_with_pushed_by.pk)
    assert obj.pk == rdp_with_pushed_by.pk
    assert obj.program.country_office.slug
    assert obj.program.beneficiary_group.master_detail in (True, False)
    assert obj.pushed_by.pk == pushed_by_user.pk


# --------------------------- dedup state helpers ----------------------------


def test_mark_rdp_dedup_finished_calls_update(mocker: MockerFixture, rdp_id: int) -> None:
    qs = mocker.MagicMock()
    mock_filter = mocker.patch.object(repo.Rdp.objects, "filter", return_value=qs)

    repo.mark_rdp_dedup_finished(rdp_id=rdp_id)

    mock_filter.assert_called_once_with(pk=rdp_id)
    qs.update.assert_called_once_with(dedup_run_state=repo.Rdp.DedupRunState.FINISHED)


def test_set_rdp_push_status_sets_fields_and_saves(mocker: MockerFixture) -> None:
    rdp = mocker.MagicMock()
    status = repo.Rdp.PushStatus.SUCCESS
    hope_rdi_id = "RID-1"

    repo.set_rdp_push_status(rdp=rdp, status=status, hope_rdi_id=hope_rdi_id)

    assert rdp.status == status
    assert rdp.hope_rdi_id == hope_rdi_id
    rdp.save.assert_called_once_with(update_fields=["status", "hope_rdi_id"])


# --------------------------- preflight_errors -------------------------------


def test_preflight_errors_empty_pks_returns_empty(mocker: MockerFixture):
    spy_rdp_qs = mocker.patch.object(repo, "rdp_pending_or_success")
    spy_hh = mocker.patch.object(repo, "households_for_preflight")
    spy_ind_hh = mocker.patch.object(repo, "individuals_for_preflight_by_households")
    spy_ind = mocker.patch.object(repo, "individuals_for_preflight_by_pks")

    assert repo.preflight_errors(pks=[], master_detail=True, exclude_rdp_id=None) == []

    spy_rdp_qs.assert_not_called()
    spy_hh.assert_not_called()
    spy_ind_hh.assert_not_called()
    spy_ind.assert_not_called()


def test_preflight_errors_master_detail_collects_errors(mocker: MockerFixture, qs, beneficiary_stub):
    hh = beneficiary_stub(pk=1, _valid=False, rdp_pre=[object()])
    ind = beneficiary_stub(pk=2, _valid=True, rdp_pre=[object()])

    sentinel_rdp_qs = object()
    mocker.patch.object(repo, "rdp_pending_or_success", return_value=sentinel_rdp_qs)

    hh_qs = qs([hh])
    ind_qs = qs([ind])

    spy_hh = mocker.patch.object(repo, "households_for_preflight", return_value=hh_qs)
    spy_ind_hh = mocker.patch.object(repo, "individuals_for_preflight_by_households", return_value=ind_qs)
    spy_ind = mocker.patch.object(repo, "individuals_for_preflight_by_pks")

    errors = repo.preflight_errors(pks=[10], master_detail=True, exclude_rdp_id=123)

    assert errors == [
        "HH #1 invalid",
        "HH #1 already in another RDP(s) (pending/success)",
        "Ind #2 already in another RDP(s) (pending/success)",
    ]
    spy_hh.assert_called_once()
    spy_ind_hh.assert_called_once()
    spy_ind.assert_not_called()


def test_preflight_errors_people_only_collects_errors(mocker: MockerFixture, qs, beneficiary_stub):
    ind = beneficiary_stub(pk=7, _valid=False, rdp_pre=[object()])

    sentinel_rdp_qs = object()
    mocker.patch.object(repo, "rdp_pending_or_success", return_value=sentinel_rdp_qs)

    spy_hh = mocker.patch.object(repo, "households_for_preflight")
    spy_ind_hh = mocker.patch.object(repo, "individuals_for_preflight_by_households")
    spy_ind = mocker.patch.object(repo, "individuals_for_preflight_by_pks", return_value=qs([ind]))

    errors = repo.preflight_errors(pks=[7], master_detail=False, exclude_rdp_id=None)

    assert errors == [
        "Ind #7 invalid",
        "Ind #7 already in another RDP(s) (pending/success)",
    ]
    spy_hh.assert_not_called()
    spy_ind_hh.assert_not_called()
    spy_ind.assert_called_once()
