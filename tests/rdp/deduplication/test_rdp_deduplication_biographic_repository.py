import pytest

from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp.deduplication.biographic.repository import (
    biographic_operation_for_rdp,
    qs_biographic_affected_individuals,
)

pytestmark = pytest.mark.django_db


def test_biographic_operation_for_rdp(
    rdp: Rdp, biographic_operation: RdpOperation, ocr_operation: RdpOperation
) -> None:
    assert biographic_operation_for_rdp(rdp=rdp) == biographic_operation


def test_biographic_operation_for_rdp_without_operation(rdp: Rdp, ocr_operation: RdpOperation) -> None:
    assert biographic_operation_for_rdp(rdp=rdp) is None


def test_qs_biographic_affected_individuals_counts_both_sides(
    people_rdp: tuple[Rdp, list[Individual]],
) -> None:
    from testutils.factories import BiographicRdpOperationFactory, BiographicRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiographicRdpOperationFactory(rdp=rdp)
    BiographicRdpOperationFindingFactory(
        operation=operation,
        individual=individuals[0],
        related_individual=individuals[1],
    )

    affected = qs_biographic_affected_individuals(operation=operation)

    assert set(affected) == {individuals[0], individuals[1]}


def test_qs_biographic_affected_individuals_ignores_other_finding_types(
    people_rdp: tuple[Rdp, list[Individual]],
) -> None:
    from testutils.factories import BiographicRdpOperationFactory, BiographicRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiographicRdpOperationFactory(rdp=rdp)
    BiographicRdpOperationFindingFactory(operation=operation, individual=individuals[0], finding_type="OTHER")

    assert not qs_biographic_affected_individuals(operation=operation).exists()


def test_qs_biographic_affected_individuals_is_distinct(
    people_rdp: tuple[Rdp, list[Individual]],
) -> None:
    from testutils.factories import BiographicRdpOperationFactory, BiographicRdpOperationFindingFactory

    rdp, individuals = people_rdp
    operation = BiographicRdpOperationFactory(rdp=rdp)
    for related in individuals[1:]:
        BiographicRdpOperationFindingFactory(operation=operation, individual=individuals[0], related_individual=related)

    assert qs_biographic_affected_individuals(operation=operation).count() == 3
