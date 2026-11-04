import pytest

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.constants import HOUSEHOLD_ROLE_REF_FIELDS
from country_workspace.models import Individual, Program, Rdp, RdpOperation, User
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.repository import (
    append_rdp_log,
    clean_rdp_selection,
    count_rdp_individuals,
    create_rdp,
    lock_rdp_for_update,
    qs_households,
    qs_individuals_for_push,
    qs_individuals_for_rdp,
    rdp_selection,
    set_rdp_beneficiaries_removed,
)
from country_workspace.rdp.types import OperationLogResult


pytestmark = pytest.mark.django_db


@pytest.fixture
def clean_members(
    rdp: Rdp, master_detail: bool, biometric_operation: RdpOperation, ocr_operation: RdpOperation
) -> list[Individual]:
    from testutils.factories import (
        BiometricRdpOperationFindingFactory,
        CountryHouseholdFactory,
        CountryIndividualFactory,
        OcrRdpOperationFindingFactory,
    )

    rdp.program.beneficiary_group.master_detail = master_detail
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])
    if master_detail:
        households = CountryHouseholdFactory.create_batch(4, batch__program=rdp.program, individuals=[])
        individuals = [CountryIndividualFactory(household=household) for household in reversed(households)]
        rdp.households.set(households)
    else:
        individuals = CountryIndividualFactory.create_batch(4, household=None, batch__program=rdp.program)
        rdp.individuals.set(individuals)

    BiometricRdpOperationFindingFactory(
        operation=biometric_operation,
        individual=individuals[0],
        related_individual=individuals[1],
        finding_type=FindingStatusCode.DUPLICATE.name,
    )
    OcrRdpOperationFindingFactory(operation=ocr_operation, individual=individuals[2])
    BiometricRdpOperationFindingFactory(
        individual=individuals[3], operation__rdp__program=rdp.program, operation__rdp__status=Rdp.PushStatus.SUCCESS
    )
    return individuals


def test_lock_rdp_for_update(rdp: Rdp) -> None:
    assert lock_rdp_for_update(pk=rdp.pk) == rdp


@pytest.mark.parametrize("master_detail", [False, True], ids=["people", "households"])
def test_rdp_selection_and_individuals(rdp: Rdp, master_detail: bool) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    rdp.program.beneficiary_group.master_detail = master_detail
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    if master_detail:
        household = CountryHouseholdFactory(batch__program=rdp.program, individuals=0)
        individuals = CountryIndividualFactory.create_batch(2, batch=household.batch, household=household)
        rdp.households.set([household])
        expected_selection = [household.pk]
    else:
        individuals = [
            CountryIndividualFactory(household=None, batch__program=rdp.program),
            CountryIndividualFactory(household=None, batch__program=rdp.program),
        ]
        rdp.individuals.set(individuals)
        expected_selection = [individual.pk for individual in individuals]

    assert rdp_selection(rdp=rdp) == (master_detail, expected_selection)
    assert list(qs_individuals_for_rdp(rdp=rdp).values_list("pk", flat=True)) == [
        individual.pk for individual in individuals
    ]
    assert count_rdp_individuals(pks=expected_selection, master_detail=master_detail) == len(individuals)


@pytest.mark.parametrize("master_detail", [False, True], ids=["people", "households"])
@pytest.mark.parametrize(
    ("operation_types", "excluded"),
    [
        ((RdpOperation.Type.BIOMETRIC_DEDUPLICATION,), (0, 1)),
        ((RdpOperation.Type.OCR,), (2,)),
    ],
)
def test_clean_rdp_selection(
    rdp: Rdp,
    clean_members: list[Individual],
    master_detail: bool,
    operation_types: tuple[RdpOperation.Type, ...],
    excluded: tuple[int, ...],
) -> None:
    operation_ids = set(rdp.operations.filter(operation_type__in=operation_types).values_list("pk", flat=True))
    expected = sorted(
        individual.household_id if master_detail else individual.pk
        for index, individual in enumerate(clean_members)
        if index not in excluded
    )

    assert clean_rdp_selection(rdp=rdp, operation_ids=operation_ids) == (master_detail, expected)


def test_create_rdp(program: Program, user: User) -> None:
    from testutils.factories import CountryIndividualFactory

    individuals = [
        CountryIndividualFactory(household=None, batch__program=program),
        CountryIndividualFactory(household=None, batch__program=program),
    ]

    rdp = create_rdp(
        config={
            "batch_name": "Test RDP",
            "country_office_id": program.country_office_id,
            "program_id": program.pk,
            "pushed_by_id": user.pk,
            "master_detail": False,
            "pks": [individual.pk for individual in individuals],
            "operations": [
                {
                    "operation_type": RdpOperation.Type.BIOMETRIC_DEDUPLICATION,
                    "config": {"threshold_type": "count", "threshold_value": "1"},
                }
            ],
        }
    )

    assert rdp.status == Rdp.PushStatus.PENDING
    assert list(rdp.individuals.order_by("pk")) == individuals

    operation = rdp.operations.get()
    assert operation.operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    assert operation.config["threshold_value"] == "1"


def test_qs_households_prefetches_ordered_members(program: Program) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    household = CountryHouseholdFactory(batch__program=program, individuals=0)
    members = CountryIndividualFactory.create_batch(2, batch=household.batch, household=household)

    [result] = list(qs_households(pks=[household.pk]))

    assert [individual.pk for individual in result.prefetched_members] == sorted(
        individual.pk for individual in members
    )


def test_qs_individuals_for_push_includes_members_and_collectors(program: Program) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    household = CountryHouseholdFactory(batch__program=program, individuals=0)
    member = CountryIndividualFactory(batch=household.batch, household=household)
    collector = CountryIndividualFactory(household=None, batch__program=program)
    household.flex_fields = {
        HOUSEHOLD_ROLE_REF_FIELDS.primary_collector: str(collector.pk),
        HOUSEHOLD_ROLE_REF_FIELDS.alternate_collector: "invalid",
    }
    household.save(update_fields=["flex_fields"])

    assert set(qs_individuals_for_push([household.pk])) == {member, collector}


@pytest.mark.parametrize("master_detail", [False, True], ids=["people", "households"])
def test_set_rdp_beneficiaries_removed(rdp: Rdp, master_detail: bool) -> None:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    rdp.program.beneficiary_group.master_detail = master_detail
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])

    if master_detail:
        household = CountryHouseholdFactory(batch__program=rdp.program, individuals=0)
        individual = CountryIndividualFactory(batch=household.batch, household=household)
        rdp.households.set([household])
    else:
        individual = CountryIndividualFactory(household=None, batch__program=rdp.program)
        rdp.individuals.set([individual])

    set_rdp_beneficiaries_removed(rdp=rdp, removed=True)

    individual.refresh_from_db()
    assert individual.removed is True

    if master_detail:
        household.refresh_from_db()
        assert household.removed is True


@pytest.mark.parametrize(
    "result",
    [None, {"success": True}],
    ids=["without_result", "with_result"],
)
def test_append_rdp_log(rdp: Rdp, result: OperationLogResult | None) -> None:
    append_rdp_log(rdp=rdp, entry_type=RdpLogEntryType.PUSH_TO_HOPE, result=result)

    rdp.refresh_from_db()
    [entry] = rdp.operation_log

    assert entry["action"] == RdpLogEntryType.PUSH_TO_HOPE.value
    assert "timestamp" in entry
    if result is None:
        assert "result" not in entry
    else:
        assert entry["result"] == result
