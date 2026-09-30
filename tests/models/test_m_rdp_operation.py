from uuid import UUID

import pytest
from django.db import IntegrityError

from country_workspace.models import RdpOperation


pytestmark = pytest.mark.django_db


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
