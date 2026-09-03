import logging
from collections.abc import Iterator
from typing import Any

from django.db import transaction
from django.utils import timezone

from country_workspace.contrib.hope.constants import DOCUMENT_TYPES, OCR_BATCH_SIZE
from country_workspace.rdp.repository import qs_individuals_for_rdp
from country_workspace.models import OcrRun, Rdp
from country_workspace.services.hope_blob import image_field_names, sync_record_blobs

from .config import OcrDocumentRequest

logger = logging.getLogger(__name__)


def rdp_for_ocr(*, pk: int) -> Rdp:
    """Return RDP with related Program loaded for the OCR workflow."""
    return Rdp.objects.select_related("program").get(pk=pk)


def resolve_ocr_documents(rdp: Rdp) -> Iterator[OcrDocumentRequest]:
    """Yield one OCR document per individual: the first populated DOCUMENT_TYPES pair.

    Individuals with no complete (image, number) pair are skipped and do not
    count toward batch_total, per docs/src/flows/rdp_ocr.md.
    """
    image_fields = image_field_names(rdp.program.individual_checker)
    for ind in qs_individuals_for_rdp(rdp=rdp).iterator(chunk_size=OCR_BATCH_SIZE):
        for doc_type in DOCUMENT_TYPES:
            image_field = f"{doc_type}_image"
            number_field = f"{doc_type}_document_number"

            pattern = ind.flex_fields.get(number_field)
            if not (isinstance(pattern, str) and pattern.strip()):
                continue
            if not ind.flex_fields.get(image_field):
                continue

            paths = sync_record_blobs(ind, image_fields, only={image_field})
            if filename := paths.get(image_field):
                yield {"individual_id": ind.pk, "filename": filename, "pattern": pattern.strip()}
            break


def lock_ocr_run_for_update(*, correlation_id: str) -> OcrRun | None:
    """Return the OcrRun locked for update, or None if the correlation_id is unknown."""
    try:
        return OcrRun.objects.select_for_update().get(correlation_id=correlation_id)
    except OcrRun.DoesNotExist:
        return None


def apply_ocr_batch_result(
    *,
    correlation_id: str,
    batch_id: str,
    batch_total: int | None,
    documents: list[dict[str, Any]],
) -> None:
    """Idempotently merge one ocr.result batch into its OcrRun.

    Redelivered batches (same batch_id already recorded) are a no-op. An
    unknown correlation_id is ignored - handle_event stays thin per the doc.
    Completion is checked against the run's own batch_total (persisted at
    publish time), not the incoming message's batch_total, so it does not
    depend on message order.
    """
    with transaction.atomic():
        run = lock_ocr_run_for_update(correlation_id=correlation_id)
        if run is None:
            logger.info("ocr.result: unknown correlation_id=%s; ignoring", correlation_id)
            return

        if batch_id in run.received_batch_ids:
            logger.info("ocr.result: batch_id=%s already received for run=%s; ignoring", batch_id, correlation_id)
            return

        if batch_total is not None and run.batch_total and batch_total != run.batch_total:
            logger.warning(
                "ocr.result: batch_total mismatch for run=%s; message=%s stored=%s",
                correlation_id,
                batch_total,
                run.batch_total,
            )

        run.received_batch_ids = [*run.received_batch_ids, batch_id]
        run.results = {**run.results, batch_id: documents}

        update_fields = ["received_batch_ids", "results"]
        if run.batch_total and len(run.received_batch_ids) >= run.batch_total:
            run.status = OcrRun.Status.COMPLETED
            run.completed_at = timezone.now()
            update_fields += ["status", "completed_at"]

        run.save(update_fields=update_fields)
