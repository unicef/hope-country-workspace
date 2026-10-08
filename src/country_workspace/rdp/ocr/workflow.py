import logging
from itertools import batched
from typing import TYPE_CHECKING
from uuid import UUID, uuid4, uuid5

from country_workspace.contrib.hope.constants import OCR_BATCH_SIZE
from country_workspace.models import RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operations.repository import (
    fail_rdp_operation_units,
    has_rdp_operation_units,
    pending_rdp_operation_units,
    prepare_rdp_operation_units_for_retry,
)
from country_workspace.rdp.repository import qs_individuals_for_rdp
from country_workspace.stream.publish import OCR_REQUEST_ROUTING_KEY, publish

from .processor import build_ocr_document_request, iter_ocr_unit_configs
from .repository import create_ocr_units

if TYPE_CHECKING:
    from .types import OcrDocumentRequest, OcrRequestMessage

logger = logging.getLogger(__name__)


def _ocr_correlation_id(operation: RdpOperation) -> UUID:
    return uuid5(operation.id, f"ocr:{operation.attempt}")


def _prepare_ocr_units(operation: RdpOperation) -> None:
    """Create OCR units once or prepare existing units for retry."""
    if has_rdp_operation_units(operation_id=operation.id):
        prepare_rdp_operation_units_for_retry(operation_id=operation.id)
        return

    individuals = qs_individuals_for_rdp(rdp=operation.rdp).only("id", "flex_fields").iterator()
    unit_configs = list(iter_ocr_unit_configs(individuals))
    if not unit_configs:
        raise RdpWorkflowError({"errors": ["OCR: no documents to process."]})

    create_ocr_units(operation=operation, unit_configs=unit_configs)


def run_ocr(operation: RdpOperation) -> None:
    """Start OCR processing for an RDP operation."""
    _prepare_ocr_units(operation)

    units = pending_rdp_operation_units(operation_id=operation.id)
    unit_count = units.count()
    if not unit_count:
        raise RdpWorkflowError({"errors": ["OCR: no pending units to process."]})

    correlation_id = str(_ocr_correlation_id(operation))
    batch_total = (unit_count + OCR_BATCH_SIZE - 1) // OCR_BATCH_SIZE
    published = 0

    for batch_index, batch in enumerate(
        batched(units.iterator(chunk_size=OCR_BATCH_SIZE), OCR_BATCH_SIZE),
        start=1,
    ):
        documents: list[OcrDocumentRequest] = []
        unit_ids: list[int] = []
        unavailable_unit_ids: list[int] = []

        for unit in batch:
            if document := build_ocr_document_request(unit):
                documents.append(document)
                unit_ids.append(unit.pk)
            else:
                unavailable_unit_ids.append(unit.pk)

        if unavailable_unit_ids:
            fail_rdp_operation_units(
                unit_ids=unavailable_unit_ids,
                error={"message": "OCR document is no longer available."},
            )

        if not documents:
            continue

        payload: OcrRequestMessage = {
            "correlation_id": correlation_id,
            "rdp_id": operation.rdp_id,
            "batch_id": str(uuid4()),
            "batch_index": batch_index,
            "batch_total": batch_total,
            "documents": documents,
        }

        if publish(OCR_REQUEST_ROUTING_KEY, payload):
            published += 1
            continue

        fail_rdp_operation_units(
            unit_ids=unit_ids,
            error={"message": "Failed to publish OCR request."},
        )
        logger.error(
            "%s: publish failed operation=%s attempt=%s batch=%s/%s",
            OCR_REQUEST_ROUTING_KEY,
            operation.id,
            operation.attempt,
            batch_index,
            batch_total,
        )

    if not published:
        raise RdpWorkflowError({"errors": ["OCR: no batches were published."]})
