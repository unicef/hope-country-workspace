import pytest

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.repository import (
    annotate_biometric_households,
    annotate_biometric_individuals,
    biometric_clean_rdp_selection,
    biometric_findings_count,
    biometric_findings_for_individual,
    biometric_operation_for_rdp,
    has_biometric_image_issues,
    qs_biometric_affected_individuals,
    qs_biometric_duplicate_individuals,
    qs_successful_biometric_operations,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def household_rdp(rdp):
    from testutils.factories import HouseholdFactory, IndividualFactory

    rdp.program.beneficiary_group.master_detail = True
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])
    households = [HouseholdFactory(batch__program=rdp.program, individuals=0) for _ in range(2)]
    members = [IndividualFactory(batch=household.batch, household=household) for household in households]
    rdp.households.set(households)
    return rdp, households, members


def test_biometric_operation_for_rdp(biometric_operation: RdpOperation) -> None:
    assert biometric_operation_for_rdp(rdp=biometric_operation.rdp) == biometric_operation


def test_successful_biometric_operations(successful_biometric_operation: RdpOperation) -> None:
    assert list(qs_successful_biometric_operations()) == [successful_biometric_operation]


def test_biometric_duplicate_and_affected_individuals(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=individuals[0],
        related_individual=individuals[1],
    )
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=individuals[2],
    )

    assert set(qs_biometric_duplicate_individuals(operation=operation)) == set(individuals[:2])
    assert set(qs_biometric_affected_individuals(operation=operation)) == set(individuals)


def test_biometric_finding_counts(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=individuals[0],
    )

    assert has_biometric_image_issues(operation=operation) is True
    assert biometric_findings_count(operation=operation) == 1


def test_clean_people_selection_excludes_affected_individual(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    BiometricRdpOperationFindingFactory(operation=operation, individual=individuals[0])

    master_detail, pks = biometric_clean_rdp_selection(operation=operation)

    assert master_detail is False
    assert pks == [individual.pk for individual in individuals[1:]]


def test_clean_household_selection_excludes_affected_household(household_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, households, members = household_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    BiometricRdpOperationFindingFactory(operation=operation, individual=members[0])

    master_detail, pks = biometric_clean_rdp_selection(operation=operation)

    assert master_detail is True
    assert pks == [households[1].pk]


def test_biometric_findings_for_individual(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=individuals[0],
        related_individual=individuals[1],
    )
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=individuals[0],
    )

    assert biometric_findings_for_individual(individual=individuals[0], rdp=rdp) == (
        [individuals[1].pk],
        [FindingStatusCode.BAD_IMAGE_QUALITY.name],
    )


def test_biometric_findings_for_individual_uses_successful_program_operations(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=individuals[0],
        related_individual=individuals[1],
    )

    assert biometric_findings_for_individual(individual=individuals[0]) == ([individuals[1].pk], [])


def test_biometric_findings_for_individual_uses_successful_household_operation(household_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, _, members = household_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=members[0],
        related_individual=members[1],
    )

    assert biometric_findings_for_individual(individual=members[0]) == ([members[1].pk], [])


def test_annotate_biometric_households_without_rdp_uses_successful_operations(household_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, households, members = household_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=members[0],
    )

    rows = {
        household.pk: household
        for household in annotate_biometric_households(
            type(households[0]).objects.filter(pk__in=[household.pk for household in households]),
            program=rdp.program,
            rdp=None,
        )
    }

    assert rows[households[0].pk]._image_issue_member_count == 1
    assert rows[households[0].pk]._result_available is True
    assert rows[households[1].pk]._image_issue_member_count == 0
    assert rows[households[1].pk]._result_available is True


def test_annotate_biometric_individuals_for_rdp(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=individuals[0],
        related_individual=individuals[1],
    )
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=individuals[2],
    )

    rows = {
        individual.pk: individual
        for individual in annotate_biometric_individuals(
            type(individuals[0]).objects.filter(pk__in=[individual.pk for individual in individuals]),
            program=rdp.program,
            rdp=rdp,
        )
    }

    assert rows[individuals[0].pk]._is_duplicate is True
    assert rows[individuals[1].pk]._is_duplicate is True
    assert rows[individuals[2].pk]._is_duplicate is False
    assert rows[individuals[2].pk]._has_image_issue is True
    assert all(row._result_available for row in rows.values())


def test_annotate_biometric_individuals_without_rdp_uses_successful_operations(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=individuals[0],
    )

    rows = {
        individual.pk: individual
        for individual in annotate_biometric_individuals(
            type(individuals[0]).objects.filter(pk__in=[individual.pk for individual in individuals]),
            program=rdp.program,
            rdp=None,
        )
    }

    assert rows[individuals[0].pk]._has_image_issue is True
    assert rows[individuals[0].pk]._result_available is True
    assert rows[individuals[1].pk]._has_image_issue is False
    assert rows[individuals[1].pk]._result_available is True


def test_annotate_biometric_households_for_rdp(household_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, BiometricRdpOperationFindingFactory

    rdp, households, members = household_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=members[0],
        related_individual=members[1],
    )
    BiometricRdpOperationFindingFactory(
        operation=operation,
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=members[1],
    )

    rows = {
        household.pk: household
        for household in annotate_biometric_households(
            type(households[0]).objects.filter(pk__in=[household.pk for household in households]),
            program=rdp.program,
            rdp=rdp,
        )
    }

    assert rows[households[0].pk]._member_count == 1
    assert rows[households[0].pk]._duplicate_member_count == 1
    assert rows[households[0].pk]._image_issue_member_count == 0
    assert rows[households[1].pk]._member_count == 1
    assert rows[households[1].pk]._duplicate_member_count == 1
    assert rows[households[1].pk]._image_issue_member_count == 1
    assert all(row._result_available for row in rows.values())
