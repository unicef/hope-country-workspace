from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pytest_mock import MockerFixture

import country_workspace.contrib.hope.push.repository as repo
from country_workspace.models import Rdp as RdpModel
from testutils.factories import (
    CountryHouseholdFactory,
    CountryIndividualFactory,
    CountryProgramFactory,
    CountryRdpFactory,
    DataSerializerFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db


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
    return (
        CountryRdpFactory(program=program_with_serializer, status=repo.Rdp.PushStatus.PENDING),
        CountryRdpFactory(program=program_with_serializer, status=repo.Rdp.PushStatus.SUCCESS),
    )


@pytest.fixture
def hh_with_members():
    hh = CountryHouseholdFactory()
    if not hh.members.exists():
        CountryIndividualFactory.create_batch(2, household=hh)
    return hh


@pytest.fixture
def hh_all_members_with_rdp(hh_with_members, rdp):
    for ind in hh_with_members.members.all():
        ind.rdp.add(rdp)
    return hh_with_members


@pytest.fixture
def two_hhs_with_rdp(rdp):
    return CountryHouseholdFactory(rdps=rdp), CountryHouseholdFactory(rdps=rdp)


@pytest.fixture
def inds3():
    return [CountryIndividualFactory() for _ in range(3)]


@pytest.fixture
def inds2_with_rdp(inds3, rdp):
    selected = inds3[:2]
    for ind in selected:
        ind.rdp.add(rdp)
    return tuple(selected)


@pytest.fixture
def rdp_with_individual_links(program_with_serializer):
    rdp = CountryRdpFactory(program=program_with_serializer)
    individuals = CountryIndividualFactory(), CountryIndividualFactory()
    for ind in individuals:
        ind.rdp.add(rdp)
    return rdp, individuals


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


@pytest.fixture
def rdp_filter_qs(mocker: MockerFixture):
    qs = MagicMock()
    mock = mocker.patch.object(repo.Rdp.objects, "filter", return_value=qs)
    return mock, qs


@pytest.fixture
def locked_rdp_chain(mocker: MockerFixture):
    qs = MagicMock()
    locked_qs = MagicMock()
    rdp = MagicMock()
    select_for_update = mocker.patch.object(repo.Rdp.objects, "select_for_update", return_value=qs)
    qs.select_related.return_value = locked_qs
    locked_qs.get.return_value = rdp
    return select_for_update, qs, locked_qs, rdp


@pytest.fixture
def preflight_spies(mocker: MockerFixture):
    return (
        mocker.patch.object(repo, "qs_rdp_pending_or_success"),
        mocker.patch.object(repo, "qs_households_for_preflight"),
        mocker.patch.object(repo, "qs_individuals_for_preflight_by_households"),
        mocker.patch.object(repo, "qs_individuals_for_preflight_by_pks"),
    )


def test_serializer_for_program_identity_when_none(program_no_serializer):
    data = {"a": 1}
    assert repo.serializer_for_program(program_no_serializer.hope_id)(data) == data


def test_serializer_for_program_uses_serializer(program_with_serializer):
    data = {"x": 1}
    assert repo.serializer_for_program(program_with_serializer.hope_id)(data) == data


def test_qs_rdp_pending_or_success_filters_and_excludes(rdp_pair):
    excluded, kept = rdp_pair
    got = set(repo.qs_rdp_pending_or_success(exclude_id=excluded.id).values_list("id", flat=True))
    assert got == {kept.id}


@pytest.mark.parametrize(
    ("builder", "pks_getter", "expected_getter"),
    [
        (
            repo.qs_individuals_by_household_pks,
            lambda hh, inds: [hh.id],
            lambda hh, inds: list(hh.members.order_by("id").values_list("id", flat=True)),
        ),
        (
            repo.qs_individuals_by_pks,
            lambda hh, inds: [inds[2].id, inds[0].id],
            lambda hh, inds: sorted([inds[0].id, inds[2].id]),
        ),
    ],
    ids=["by_hh", "by_pks"],
)
def test_qs_individuals_filters_and_ordering(builder, pks_getter, expected_getter, hh_with_members, inds3):
    got = list(builder(pks_getter(hh_with_members, inds3)).values_list("id", flat=True))
    assert got == expected_getter(hh_with_members, inds3)


@pytest.mark.parametrize("prefetch_members", [True, False], ids=["prefetch", "noprefetch"])
def test_qs_households_prefetch_members_toggle(hh_with_members, prefetch_members):
    items = list(repo.qs_households(pks=[hh_with_members.id], prefetch_members=prefetch_members))
    assert all(hasattr(h, "prefetched_members") is prefetch_members for h in items)


@pytest.mark.parametrize(
    ("builder", "kwargs"),
    [
        (repo.qs_individuals_for_preflight_by_pks, lambda src, rdp_qs: {"pks": [i.id for i in src], "rdp_qs": rdp_qs}),
        (
            repo.qs_individuals_for_preflight_by_households,
            lambda src, rdp_qs: {"hh_pks": [src.id], "rdp_qs": rdp_qs},
        ),
        (repo.qs_households_for_preflight, lambda src, rdp_qs: {"pks": [h.id for h in src], "rdp_qs": rdp_qs}),
    ],
    ids=["inds_by_pks", "inds_by_hhs", "hhs"],
)
def test_preflight_query_builders_prefetch_rdp(
    builder, kwargs, inds2_with_rdp, hh_all_members_with_rdp, two_hhs_with_rdp, rdp_qs, rdp
):
    source = {
        repo.qs_individuals_for_preflight_by_pks: inds2_with_rdp,
        repo.qs_individuals_for_preflight_by_households: hh_all_members_with_rdp,
        repo.qs_households_for_preflight: two_hhs_with_rdp,
    }[builder]
    rows = list(builder(**kwargs(source, rdp_qs)))
    assert rows
    assert all([x.pk for x in row.rdp_pre] == [rdp.pk] for row in rows)


def test_rdp_selection_prefers_households(two_hhs_with_rdp):
    h1, h2 = two_hhs_with_rdp
    assert repo.rdp_selection(rdp=h1.rdp.first()) == (True, [h1.pk, h2.pk])


def test_rdp_selection_falls_back_to_individuals(rdp_with_individual_links):
    rdp, (i1, i2) = rdp_with_individual_links
    assert repo.rdp_selection(rdp=rdp) == (False, [i1.pk, i2.pk])


@pytest.mark.parametrize(
    ("fixture_name", "expected_getter"),
    [
        (
            "rdp_with_household_link",
            lambda selection: list(repo.qs_individuals_by_household_pks([selection.pk]).values_list("id", flat=True)),
        ),
        (
            "rdp_with_individual_links",
            lambda selection: list(
                repo.qs_individuals_by_pks([selection[0].pk, selection[1].pk]).values_list("id", flat=True)
            ),
        ),
    ],
    ids=["by_households", "by_pks"],
)
def test_qs_individuals_for_rdp_uses_selection(request: pytest.FixtureRequest, fixture_name, expected_getter):
    rdp, selection = request.getfixturevalue(fixture_name)
    assert list(repo.qs_individuals_for_rdp(rdp=rdp).values_list("id", flat=True)) == expected_getter(selection)


@pytest.mark.parametrize(
    ("fixture_name", "master_detail", "expected_pks"),
    [
        ("rdp_with_household_link", True, lambda selection: [selection.pk]),
        ("rdp_with_individual_links", False, lambda selection: [selection[0].pk, selection[1].pk]),
    ],
    ids=["master_detail", "people_only"],
)
def test_workflow_config_for_rdp_builds_expected(
    request: pytest.FixtureRequest,
    fixture_name: str,
    master_detail: bool,
    expected_pks,
):
    rdp, selection = request.getfixturevalue(fixture_name)
    imported_by_email = "u@example.com"

    assert repo.workflow_config_for_rdp(rdp=rdp, imported_by_email=imported_by_email) == {
        "batch_name": rdp.name,
        "co_slug": rdp.program.country_office.slug,
        "imported_by_email": imported_by_email,
        "master_detail": master_detail,
        "pks": expected_pks(selection),
        "program_hope_id": rdp.program.hope_id,
        "rdp_id": rdp.pk,
    }


def test_rdp_for_dedup_returns_rdp_with_program(rdp):
    obj = repo.rdp_for_dedup(pk=rdp.pk)
    assert (obj.pk, obj.program.pk) == (rdp.pk, rdp.program.pk)


def test_rdp_for_push_returns_rdp_with_required_relations(rdp_with_pushed_by, pushed_by_user):
    obj = repo.rdp_for_push(pk=rdp_with_pushed_by.pk)
    assert obj.pk == rdp_with_pushed_by.pk
    assert obj.program.country_office.slug
    assert obj.program.beneficiary_group.master_detail in (True, False)
    assert obj.pushed_by.pk == pushed_by_user.pk


def test_lock_rdp_for_update_locks_rdp_with_program(locked_rdp_chain, rdp_id: int) -> None:
    select_for_update, qs, locked_qs, rdp = locked_rdp_chain

    assert repo.lock_rdp_for_update(pk=rdp_id) is rdp
    select_for_update.assert_called_once_with()
    qs.select_related.assert_called_once_with("program")
    locked_qs.get.assert_called_once_with(pk=rdp_id)


@pytest.mark.parametrize(
    "deduplication_set_id",
    [None, UUID("11111111-1111-1111-1111-111111111111")],
    ids=["without_set_id", "with_set_id"],
)
def test_set_rdp_dedup_state_updates_expected_fields(
    rdp_filter_qs,
    rdp_id: int,
    deduplication_set_id: UUID | None,
) -> None:
    mock_filter, qs = rdp_filter_qs
    expected = {"dedup_run_state": repo.Rdp.DedupRunState.FINISHED}
    if deduplication_set_id is not None:
        expected["deduplication_set_id"] = deduplication_set_id

    repo.set_rdp_dedup_state(
        rdp_id=rdp_id,
        state=repo.Rdp.DedupRunState.FINISHED,
        deduplication_set_id=deduplication_set_id,
    )

    mock_filter.assert_called_once_with(pk=rdp_id)
    qs.update.assert_called_once_with(**expected)


def test_set_rdp_push_status_sets_fields_and_saves() -> None:
    rdp = MagicMock()

    repo.set_rdp_push_status(
        rdp=rdp,
        status=repo.Rdp.PushStatus.SUCCESS,
        hope_rdi_id="RID-1",
    )

    assert (rdp.status, rdp.hope_rdi_id) == (repo.Rdp.PushStatus.SUCCESS, "RID-1")
    rdp.save.assert_called_once_with(update_fields=["status", "hope_rdi_id"])


def test_preflight_errors_empty_pks_returns_empty(preflight_spies):
    assert repo.preflight_errors(pks=[], master_detail=True, exclude_rdp_id=None) == []
    for spy in preflight_spies:
        spy.assert_not_called()


def test_preflight_errors_master_detail_collects_errors(mocker: MockerFixture, qs, beneficiary_stub):
    mocker.patch.object(repo, "qs_rdp_pending_or_success", return_value=object())
    spy_hh = mocker.patch.object(
        repo,
        "qs_households_for_preflight",
        return_value=qs([beneficiary_stub(pk=1, _valid=False, rdp_pre=[object()])]),
    )
    spy_ind_hh = mocker.patch.object(
        repo,
        "qs_individuals_for_preflight_by_households",
        return_value=qs([beneficiary_stub(pk=2, _valid=True, rdp_pre=[object()])]),
    )
    spy_ind = mocker.patch.object(repo, "qs_individuals_for_preflight_by_pks")

    assert repo.preflight_errors(pks=[10], master_detail=True, exclude_rdp_id=123) == [
        "HH #1 invalid",
        "HH #1 already in another RDP(s) (pending/success)",
        "Ind #2 already in another RDP(s) (pending/success)",
    ]
    spy_hh.assert_called_once()
    spy_ind_hh.assert_called_once()
    spy_ind.assert_not_called()


def test_preflight_errors_people_only_collects_errors(mocker: MockerFixture, qs, beneficiary_stub):
    mocker.patch.object(repo, "qs_rdp_pending_or_success", return_value=object())
    spy_hh = mocker.patch.object(repo, "qs_households_for_preflight")
    spy_ind_hh = mocker.patch.object(repo, "qs_individuals_for_preflight_by_households")
    spy_ind = mocker.patch.object(
        repo,
        "qs_individuals_for_preflight_by_pks",
        return_value=qs([beneficiary_stub(pk=7, _valid=False, rdp_pre=[object()])]),
    )

    assert repo.preflight_errors(pks=[7], master_detail=False, exclude_rdp_id=None) == [
        "Ind #7 invalid",
        "Ind #7 already in another RDP(s) (pending/success)",
    ]
    spy_hh.assert_not_called()
    spy_ind_hh.assert_not_called()
    spy_ind.assert_called_once()
