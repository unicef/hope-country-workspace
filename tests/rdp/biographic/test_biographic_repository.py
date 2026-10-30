import pytest

from country_workspace.models import Individual, RdpOperation
from country_workspace.rdp.biographic import repository

pytestmark = pytest.mark.django_db


@pytest.fixture
def finding_setup(successful_biographic_operation, people_rdp):
    from testutils.factories import BiographicRdpOperationFindingFactory, IndividualFactory

    rdp, individuals = people_rdp
    RdpOperation.objects.filter(pk=successful_biographic_operation.pk).update(rdp=rdp)
    successful_biographic_operation.refresh_from_db()
    outside = IndividualFactory(household=None, batch__program=rdp.program)
    BiographicRdpOperationFindingFactory(
        operation=successful_biographic_operation,
        individual=individuals[0],
        related_individual=individuals[1],
        details={"score": 0.9, "scope": "batch", "matched_full_name": "Two"},
    )
    BiographicRdpOperationFindingFactory(
        operation=successful_biographic_operation,
        individual=individuals[1],
        related_individual=individuals[0],
        details={"score": 0.8, "scope": "batch", "matched_full_name": "One"},
    )
    BiographicRdpOperationFindingFactory(
        operation=successful_biographic_operation,
        individual=individuals[2],
        related_individual=outside,
        details={"score": 0.7, "scope": "population", "matched_full_name": "Outside"},
    )
    return rdp, individuals, outside, successful_biographic_operation


def test_operation_lookups(rdp, successful_biographic_operation, successful_biometric_operation) -> None:
    assert repository.biographic_operation_for_rdp(rdp=rdp) == successful_biographic_operation
    assert list(repository.qs_successful_biographic_operations()) == [successful_biographic_operation]


def test_operation_for_rdp_without_operation(rdp) -> None:
    assert repository.biographic_operation_for_rdp(rdp=rdp) is None


def test_affected_and_duplicate_individuals(finding_setup) -> None:
    _, individuals, outside, operation = finding_setup

    affected = set(repository.qs_biographic_affected_individuals(operation=operation))
    duplicates = set(repository.qs_biographic_duplicate_individuals(operation=operation))

    assert affected == set(individuals)
    assert duplicates == {*individuals, outside}
    assert repository.biographic_findings_count(operation=operation) == 3


def test_findings_for_individual(finding_setup) -> None:
    rdp, individuals, outside, _ = finding_setup

    [match] = repository.biographic_findings_for_individual(individual=individuals[0], rdp=rdp)

    assert match == {"pk": individuals[1].pk, "rdp_id": rdp.pk, "score": 0.9, "scope": "batch", "full_name": "Two"}
    [outside_match] = repository.biographic_findings_for_individual(individual=outside)
    assert outside_match["pk"] == individuals[2].pk


def test_findings_for_individual_ignores_unsuccessful_operations(finding_setup) -> None:
    _, individuals, _, operation = finding_setup
    RdpOperation.objects.filter(pk=operation.pk).update(status=RdpOperation.Status.FAILURE)

    assert repository.biographic_findings_for_individual(individual=individuals[0]) == []


def test_annotate_individuals_for_rdp(finding_setup) -> None:
    rdp, individuals, outside, _ = finding_setup

    rows = {
        i.pk: (i._is_biographic_duplicate, i._biographic_result_available)
        for i in repository.annotate_biographic_individuals(
            Individual.objects.filter(pk__in=[*(i.pk for i in individuals), outside.pk]),
            program=rdp.program,
            rdp=rdp,
        )
    }

    assert rows[individuals[0].pk] == (True, True)
    assert rows[outside.pk] == (True, True)


def test_annotate_individuals_for_program(finding_setup) -> None:
    rdp, individuals, _, _ = finding_setup

    rows = {
        i.pk: (i._is_biographic_duplicate, i._biographic_result_available)
        for i in repository.annotate_biographic_individuals(
            Individual.objects.filter(pk__in=[i.pk for i in individuals]),
            program=rdp.program,
            rdp=None,
        )
    }

    assert all(duplicate and available for duplicate, available in rows.values())


@pytest.mark.parametrize("with_rdp", [True, False])
def test_annotate_households(finding_setup, with_rdp: bool) -> None:
    from country_workspace.models import Household

    rdp, _, _, _ = finding_setup

    rows = list(
        repository.annotate_biographic_households(
            Household.objects.filter(batch__program=rdp.program),
            program=rdp.program,
            rdp=rdp if with_rdp else None,
        )
    )

    assert all(hasattr(h, "_biographic_member_count") for h in rows)
    assert all(h._biographic_selected_rdp_id == (rdp.pk if with_rdp else None) for h in rows)
