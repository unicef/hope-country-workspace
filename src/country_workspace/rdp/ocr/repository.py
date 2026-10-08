from itertools import batched

from django.db import transaction

from country_workspace.models import RdpOperation, RdpOperationUnit

from .constants import OCR_UNIT_BULK_CREATE_BATCH_SIZE
from .types import OcrUnitConfig


def create_ocr_units(
    *,
    operation: RdpOperation,
    unit_configs: list[tuple[int, OcrUnitConfig]],
) -> None:
    """Persist OCR operation units."""
    units = (
        RdpOperationUnit(operation=operation, individual_id=individual_id, config=config)
        for individual_id, config in unit_configs
    )

    with transaction.atomic():
        for batch in batched(units, OCR_UNIT_BULK_CREATE_BATCH_SIZE):
            RdpOperationUnit.objects.bulk_create(batch)
