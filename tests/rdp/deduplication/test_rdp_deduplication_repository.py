from functools import partial

import pytest

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp.deduplication.repository import (
    biometric_operation_for_rdp,
    qs_biometric_affected_individuals,
    rdp_for_dedup,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def affected_individuals(
    people_rdp: tuple[Rdp, list[Individual]], biometric_operation: RdpOperation
) -> list[Individual]:
    from testutils.factories import (
        BiometricRdpOperationFindingFactory,
        IndividualFactory,
        OcrRdpOperationFindingFactory,
    )

    rdp, individuals = people_rdp
    outside = IndividualFactory(household=None, batch__program=rdp.program)
    unaffected = IndividualFactory(household=None, batch__program=rdp.program, rdps=[rdp])
    finding = partial(BiometricRdpOperationFindingFactory, operation=biometric_operation)
    finding(
        individual=individuals[0],
        related_individual=individuals[1],
        finding_type=FindingStatusCode.DUPLICATE.name,
    )
    finding(
        individual=individuals[0],
        related_individual=outside,
        finding_type=FindingStatusCode.DUPLICATE.name,
    )
    finding(individual=individuals[0])
    finding(individual=individuals[2])
    finding(individual=unaffected, finding_type=FindingStatusCode.GENERIC_ERROR.name)
    BiometricRdpOperationFindingFactory(
        individual=unaffected,
        operation__rdp__program=rdp.program,
        operation__rdp__status=Rdp.PushStatus.SUCCESS,
    )
    OcrRdpOperationFindingFactory(individual=unaffected, operation__rdp=rdp)
    return individuals


def test_rdp_for_dedup(rdp: Rdp) -> None:
    assert rdp_for_dedup(pk=rdp.pk) == rdp


def test_biometric_operation_for_rdp(biometric_operation: RdpOperation) -> None:
    assert biometric_operation_for_rdp(rdp=biometric_operation.rdp) == biometric_operation


def test_biometric_operation_for_rdp_ignores_other_types(ocr_operation: RdpOperation) -> None:
    assert biometric_operation_for_rdp(rdp=ocr_operation.rdp) is None


def test_biometric_affected_individuals(
    biometric_operation: RdpOperation, affected_individuals: list[Individual]
) -> None:
    assert list(qs_biometric_affected_individuals(operation=biometric_operation)) == affected_individuals
