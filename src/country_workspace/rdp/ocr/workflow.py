import logging
from collections.abc import Iterable
from itertools import batched
from typing import TYPE_CHECKING
from uuid import UUID, uuid4, uuid5

from django.db import transaction

from country_workspace.contrib.hope.constants import OCR_BATCH_SIZE
from country_workspace.models import RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.operations.completion import complete_rdp_operation, finalize_rdp_operation_from_units
from country_workspace.rdp.operations.repository import (
    fail_rdp_operation_units,
    has_rdp_operation_units,
    lock_current_rdp_operation,
    pending_rdp_operation_units,
    prepare_rdp_operation_units_for_retry,
)
from country_workspace.rdp.repository import qs_individuals_for_rdp
from country_workspace.stream.publish import OCR_REQUEST_ROUTING_KEY, publish

from .processor import build_ocr_document_request, iter_ocr_unit_configs
from .repository import create_ocr_units

if TYPE_CHECKING:
    from country_workspace.models import RdpOperationUnit
    from .types import OcrDocumentRequest, OcrRequestMessage

logger = logging.getLogger(__name__)


def _ocr_correlation_id(operation: RdpOperation) -> UUID:
    return uuid5(operation.id, f"ocr:{operation.attempt}")


def _prepare_ocr_units(operation: RdpOperation) -> bool:
    """Create or reset OCR units only while the execution attempt is current."""
    if has_rdp_operation_units(operation_id=operation.id):
        return prepare_rdp_operation_units_for_retry(operation_id=operation.id, expected_attempt=operation.attempt)

    individuals = qs_individuals_for_rdp(rdp=operation.rdp).only("id", "flex_fields").iterator()
    return create_ocr_units(operation=operation, unit_configs=list(iter_ocr_unit_configs(individuals)))


def _prepare_ocr_batch(
    operation: RdpOperation,
    units: Iterable["RdpOperationUnit"],
) -> list["OcrDocumentRequest"]:
    """Build OCR documents and fail units whose documents are unavailable."""
    documents: list[OcrDocumentRequest] = []
    unavailable_unit_ids: list[int] = []

    for unit in units:
        if document := build_ocr_document_request(unit):
            documents.append(document)
        else:
            unavailable_unit_ids.append(unit.pk)

    if unavailable_unit_ids:
        fail_rdp_operation_units(
            operation_id=operation.id,
            expected_attempt=operation.attempt,
            unit_ids=unavailable_unit_ids,
            error={"message": "OCR document is no longer available."},
        )

    return documents


def run_ocr(operation: RdpOperation) -> None:
    """Start OCR processing for an RDP operation."""
    if not _prepare_ocr_units(operation):
        return

    if not has_rdp_operation_units(operation_id=operation.id):
        complete_rdp_operation(operation=operation)
        return

    units = pending_rdp_operation_units(operation_id=operation.id)
    unit_count = units.count()
    if not unit_count:
        finalize_rdp_operation_from_units(operation=operation)
        return

    correlation_id = str(_ocr_correlation_id(operation))
    batch_total = (unit_count + OCR_BATCH_SIZE - 1) // OCR_BATCH_SIZE
    publish_failed = False

    for batch_index, batch in enumerate(
        batched(units.iterator(chunk_size=OCR_BATCH_SIZE), OCR_BATCH_SIZE),
        start=1,
    ):
        if not (documents := _prepare_ocr_batch(operation, batch)):
            continue

        payload: OcrRequestMessage = {
            "correlation_id": correlation_id,
            "rdp_id": operation.rdp_id,
            "batch_id": str(uuid4()),
            "batch_index": batch_index,
            "batch_total": batch_total,
            "documents": documents,
        }

        with transaction.atomic():
            if lock_current_rdp_operation(operation_id=operation.id, expected_attempt=operation.attempt) is None:
                return

        if publish(OCR_REQUEST_ROUTING_KEY, payload):
            continue

        publish_failed = True
        logger.error(
            "%s: publish failed operation=%s attempt=%s batch=%s/%s",
            OCR_REQUEST_ROUTING_KEY,
            operation.id,
            operation.attempt,
            batch_index,
            batch_total,
        )

    if publish_failed:
        raise RdpWorkflowError({"errors": ["OCR: failed to publish one or more batches."]})

    finalize_rdp_operation_from_units(operation=operation)
