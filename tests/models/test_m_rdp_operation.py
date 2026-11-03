from uuid import UUID

import pytest
from django.db import IntegrityError

from country_workspace.models import RdpOperation, RdpOperationUnit


pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp_operation_unit() -> RdpOperationUnit:
    from testutils.factories import IndividualFactory, OcrRdpOperationFactory

    operation = OcrRdpOperationFactory()
    individual = IndividualFactory(household=None, batch__program=operation.rdp.program)
    return RdpOperationUnit.objects.create(operation=operation, individual=individual)


def test_rdp_operation_defaults(rdp_operation: RdpOperation) -> None:
    assert isinstance(rdp_operation.pk, UUID)
    assert rdp_operation.status == RdpOperation.Status.PENDING
    assert rdp_operation.attempt == 0
    assert rdp_operation.config == {}
    assert rdp_operation.error == {}
    assert rdp_operation.log == []


def test_rdp_operation_type_is_unique_per_rdp(rdp_operation: RdpOperation) -> None:
    with pytest.raises(IntegrityError):
        RdpOperation.objects.create(
            rdp=rdp_operation.rdp,
            operation_type=rdp_operation.operation_type,
        )


def test_rdp_allows_different_operation_types(rdp_operation: RdpOperation) -> None:
    operation_type = (
        RdpOperation.Type.OCR
        if rdp_operation.operation_type == RdpOperation.Type.BIOMETRIC_DEDUPLICATION
        else RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    )

    RdpOperation.objects.create(rdp=rdp_operation.rdp, operation_type=operation_type)

    assert rdp_operation.rdp.operations.count() == 2


def test_rdp_operation_unit_defaults(rdp_operation_unit: RdpOperationUnit) -> None:
    assert rdp_operation_unit.status == RdpOperationUnit.Status.PENDING
    assert rdp_operation_unit.config == {}
    assert rdp_operation_unit.error == {}


def test_rdp_operation_unit_is_unique_per_individual(rdp_operation_unit: RdpOperationUnit) -> None:
    with pytest.raises(IntegrityError):
        RdpOperationUnit.objects.create(
            operation=rdp_operation_unit.operation,
            individual=rdp_operation_unit.individual,
        )
