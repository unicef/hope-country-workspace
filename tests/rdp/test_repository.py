import pytest
from django.db import transaction

from country_workspace.models import Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.repository import (
    append_rdp_operation_log,
    collector_pks_by_household_pks,
    lock_rdp_for_update,
    qs_households,
    qs_individuals_by_household_pks,
    qs_individuals_by_pks,
    qs_individuals_for_push,
    qs_individuals_for_rdp,
    rdp_selection,
    set_rdp_beneficiaries_removed,
    set_rdp_push_status,
)
from country_workspace.workspaces.models import CountryHousehold


pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp(user) -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(pushed_by=user)


@pytest.fixture
def households() -> tuple[CountryHousehold, CountryHousehold]:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    households = CountryHouseholdFactory.create_batch(2)
    for household in households:
        if not household.members.exists():
            CountryIndividualFactory(household=household, batch=household.batch)
    return tuple(households)


@pytest.fixture(params=["households", "pks"], ids=["by_household", "by_pks"])
def individual_query_case(request: pytest.FixtureRequest):
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    if request.param == "households":
        household = CountryHouseholdFactory()
        if not household.members.exists():
            CountryIndividualFactory.create_batch(2, household=household, batch=household.batch)
        return (
            qs_individuals_by_household_pks,
            [household.pk],
            list(household.members.order_by("id").values_list("pk", flat=True)),
        )

    individuals = CountryIndividualFactory.create_batch(3)
    return (
        qs_individuals_by_pks,
        [individuals[2].pk, individuals[0].pk],
        sorted([individuals[0].pk, individuals[2].pk]),
    )


@pytest.fixture(params=[True, False], ids=["households", "people"])
def rdp_case(request: pytest.FixtureRequest, user):
    from testutils.factories import (
        CountryHouseholdFactory,
        CountryIndividualFactory,
        CountryProgramFactory,
        CountryRdpFactory,
    )

    master_detail = request.param
    program = CountryProgramFactory(beneficiary_group__master_detail=master_detail)
    rdp = CountryRdpFactory(program=program, pushed_by=user)

    if master_detail:
        selected = CountryHouseholdFactory.create_batch(2, batch__program=program, rdps=rdp)
        for household in selected:
            if not household.members.exists():
                CountryIndividualFactory(household=household, batch=household.batch)
        individuals = [individual for household in selected for individual in household.members.all()]
    else:
        selected = CountryIndividualFactory.create_batch(2, batch__program=program)
        for individual in selected:
            individual.rdp.add(rdp)
        individuals = selected

    return rdp, master_detail, selected, individuals


def test_lock_rdp_for_update(rdp: Rdp) -> None:
    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)

    assert locked == rdp
    assert locked.program == rdp.program


def test_qs_households(households) -> None:
    first, second = households

    result = list(qs_households(pks=[second.pk, first.pk]))

    assert [household.pk for household in result] == sorted([first.pk, second.pk])
    for household in result:
        assert [individual.pk for individual in household.prefetched_members] == list(
            household.members.order_by("id").values_list("pk", flat=True)
        )


def test_qs_individuals(individual_query_case) -> None:
    builder, pks, expected = individual_query_case

    assert list(builder(pks).values_list("pk", flat=True)) == expected


def test_rdp_selection_and_individuals(rdp_case) -> None:
    rdp, master_detail, selected, individuals = rdp_case

    assert rdp_selection(rdp=rdp) == (master_detail, sorted(item.pk for item in selected))
    assert list(qs_individuals_for_rdp(rdp=rdp).values_list("pk", flat=True)) == sorted(
        individual.pk for individual in individuals
    )


def test_set_rdp_beneficiaries_removed(rdp_case) -> None:
    rdp, master_detail, selected, individuals = rdp_case

    set_rdp_beneficiaries_removed(rdp=rdp, removed=True)

    for individual in individuals:
        individual.refresh_from_db()
        assert individual.removed is True

    if master_detail:
        for household in selected:
            household.refresh_from_db()
            assert household.removed is True


def test_collector_pks_by_household_pks_returns_role_ref_pks() -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory()
    hh.members.all().delete()
    primary = CountryIndividualFactory(household=None)
    alternate = CountryIndividualFactory(household=None)
    hh.flex_fields = {"primary_collector_id": primary.pk, "alternate_collector_id": alternate.pk}
    hh.save(update_fields=["flex_fields"])

    assert collector_pks_by_household_pks([hh.pk]) == {primary.pk, alternate.pk}


def test_collector_pks_by_household_pks_ignores_missing_and_invalid_refs() -> None:
    from testutils.factories import CountryHouseholdFactory

    hh = CountryHouseholdFactory()
    hh.members.all().delete()
    hh.flex_fields = {"primary_collector_id": None, "alternate_collector_id": "not-a-pk"}
    hh.save(update_fields=["flex_fields"])

    assert collector_pks_by_household_pks([hh.pk]) == set()


def test_qs_individuals_for_push_includes_members_and_referenced_collectors() -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    hh = CountryHouseholdFactory()
    hh.members.all().delete()
    member = CountryIndividualFactory(household=hh)
    collector = CountryIndividualFactory(household=None, flex_fields={"relationship": "NON_BENEFICIARY"})
    unreferenced = CountryIndividualFactory(household=None)
    hh.flex_fields = {"primary_collector_id": collector.pk}
    hh.save(update_fields=["flex_fields"])

    result = set(qs_individuals_for_push([hh.pk]).values_list("id", flat=True))

    assert result == {member.pk, collector.pk}
    assert unreferenced.pk not in result


@pytest.mark.parametrize("dedup_lock", [None, False], ids=["keep_dedup_lock", "update_dedup_lock"])
def test_set_rdp_push_status(rdp: Rdp, dedup_lock: bool | None) -> None:
    rdp.is_dedup_settings_locked = True
    rdp.save(update_fields=["is_dedup_settings_locked"])

    set_rdp_push_status(
        rdp=rdp,
        status=Rdp.PushStatus.SUCCESS,
        hope_rdi_id="RID",
        is_dedup_settings_locked=dedup_lock,
    )

    rdp.refresh_from_db()

    assert rdp.status == Rdp.PushStatus.SUCCESS
    assert rdp.hope_rdi_id == "RID"
    assert rdp.is_dedup_settings_locked is (True if dedup_lock is None else dedup_lock)


@pytest.mark.parametrize("full", [False, True], ids=["minimal", "full"])
def test_append_rdp_operation_log(rdp: Rdp, full: bool) -> None:
    existing = [{"action": "EXISTING"}] if full else None
    rdp.operation_log = existing

    append_rdp_operation_log(
        rdp=rdp,
        action=RdpOperationAction.START_DEDUPLICATION,
        result={"ok": True} if full else None,
    )

    rdp.refresh_from_db()
    entry = rdp.operation_log[-1]

    assert rdp.operation_log[:-1] == (existing or [])
    assert entry["action"] == RdpOperationAction.START_DEDUPLICATION.value
    assert entry["timestamp"]
    assert ("result" in entry) is full
