from itertools import batched
from uuid import UUID

from django.db import transaction

from country_workspace.models import RdpOperation, RdpOperationUnit
from country_workspace.rdp.operations.repository import lock_current_rdp_operation

from .constants import OCR_UNIT_BULK_CREATE_BATCH_SIZE
from .types import OcrUnitConfig


def create_ocr_units(
    *,
    operation: RdpOperation,
    unit_configs: list[tuple[int, OcrUnitConfig]],
) -> bool:
    """Persist OCR units only for the expected running attempt."""
    units = (
        RdpOperationUnit(operation=operation, individual_id=individual_id, config=config)
        for individual_id, config in unit_configs
    )
    with transaction.atomic():
        if lock_current_rdp_operation(operation_id=operation.id, expected_attempt=operation.attempt) is None:
            return False
        for batch in batched(units, OCR_UNIT_BULK_CREATE_BATCH_SIZE):
            RdpOperationUnit.objects.bulk_create(batch)
    return True


def lock_ocr_operation_for_update(*, rdp_id: int) -> RdpOperation | None:
    """Return the OCR operation locked for update."""
    try:
        return RdpOperation.objects.select_for_update().get(
            rdp_id=rdp_id,
            operation_type=RdpOperation.Type.OCR,
        )
    except RdpOperation.DoesNotExist:
        return None


def lock_pending_ocr_units(
    *,
    operation_id: UUID,
    individual_ids: set[int],
) -> dict[int, RdpOperationUnit]:
    """Return pending OCR units locked by individual ID."""
    return {
        unit.individual_id: unit
        for unit in RdpOperationUnit.objects.select_for_update().filter(
            operation_id=operation_id,
            status=RdpOperationUnit.Status.PENDING,
            individual_id__in=individual_ids,
        )
    }
