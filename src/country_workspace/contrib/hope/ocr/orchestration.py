import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from django.db import IntegrityError, transaction

from country_workspace.contrib.hope.constants import OCR_BATCH_SIZE
from country_workspace.models import AsyncJob, OcrRun, Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.repository import append_rdp_operation_log, lock_rdp_for_update
from country_workspace.stream.publish import OCR_REQUEST_ROUTING_KEY, publish

from .policy import get_ocr_policy
from .repository import apply_ocr_batch_result, rdp_for_ocr, resolve_ocr_documents

if TYPE_CHECKING:
    from .config import OcrRequestMessage

logger = logging.getLogger(__name__)


def claim_rdp_ocr(rdp_id: int) -> tuple[ActionCheck, Rdp | None]:
    """Claim OCR for an RDP by creating its OcrRun row under a lock on the RDP.

    OcrRun.rdp's OneToOne uniqueness is what actually enforces "one OCR run
    per RDP, ever"; the RDP row lock only serializes concurrent claims so the
    check-then-create below is race-free.
    """
    rdp = rdp_for_ocr(pk=rdp_id)
    check = get_ocr_policy(rdp).ocr_check()
    if not check.allowed:
        return check, None

    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp_id)
        if OcrRun.objects.filter(rdp=locked).exists():
            return ActionCheck(False, "RDP: OCR has already been run for this RDP."), None
        try:
            OcrRun.objects.create(rdp=locked)
        except IntegrityError:
            return ActionCheck(False, "RDP: OCR has already been run for this RDP."), None

    return ActionCheck(True), locked


def get_batches(documents: list[dict], size: int) -> list[list[dict]]:
    return [documents[i : i + size] for i in range(0, len(documents), size)]


def _log_ocr_operation(*, rdp: Rdp, result: dict[str, Any]) -> None:
    with transaction.atomic():
        locked = lock_rdp_for_update(pk=rdp.pk)
        append_rdp_operation_log(
            rdp=locked,
            action=RdpOperationAction.START_OCR,
            result=result,
        )


def run_ocr_core(job: AsyncJob) -> dict[str, Any]:
    """Resolve RDP documents and publish batched ocr.request messages.

    The OcrRun row is created by claim_rdp_ocr before this job is queued;
    this only resolves documents, batches them, and publishes.
    """
    rdp_id = job.config["rdp_id"]
    rdp = rdp_for_ocr(pk=rdp_id)
    ocr_run = rdp.ocr_run

    documents = list(resolve_ocr_documents(rdp))
    batches = get_batches(documents, OCR_BATCH_SIZE)

    if not batches:
        OcrRun.objects.filter(pk=ocr_run.pk).update(status=OcrRun.Status.FAILED)
        _log_ocr_operation(
            rdp=rdp,
            result={"error": "no documents with both an image and a document number"},
        )
        raise RdpWorkflowError({"errors": ["OCR: no documents to process"]})

    batch_total = len(batches)
    OcrRun.objects.filter(pk=ocr_run.pk).update(batch_total=batch_total)

    published = 0
    for index, batch in enumerate(batches, start=1):
        payload: OcrRequestMessage = {
            "correlation_id": str(ocr_run.correlation_id),
            "rdp_id": rdp.pk,
            "batch_id": str(uuid4()),
            "batch_index": index,
            "batch_total": batch_total,
            "documents": batch,
        }
        if not publish(OCR_REQUEST_ROUTING_KEY, payload):
            logger.error(
                "%s: publish failed for run=%s batch_index=%s/%s",
                OCR_REQUEST_ROUTING_KEY,
                ocr_run.correlation_id,
                index,
                batch_total,
            )
            break
        published += 1

    succeeded = published == batch_total
    OcrRun.objects.filter(pk=ocr_run.pk).update(status=OcrRun.Status.IN_PROGRESS if succeeded else OcrRun.Status.FAILED)
    _log_ocr_operation(
        rdp=rdp,
        result={
            "correlation_id": str(ocr_run.correlation_id),
            "batch_total": batch_total,
            "batches_published": published,
        },
    )

    if not succeeded:
        # batch_total was already persisted, so results can still complete the
        # run later even though this publish attempt was only partial.
        raise RdpWorkflowError({"errors": [f"OCR: publish failed after {published}/{batch_total} batches"]})

    return {"correlation_id": str(ocr_run.correlation_id), "batch_total": batch_total, "batches_published": published}


def handle_ocr_result(payload: dict[str, Any]) -> None:
    """Consume-side entry point for the ocr.result routing key. Stays thin."""
    correlation_id = payload.get("correlation_id")
    batch_id = payload.get("batch_id")
    if not correlation_id or not batch_id:
        logger.warning("ocr.result: missing correlation_id/batch_id; payload=%r", payload)
        return

    apply_ocr_batch_result(
        correlation_id=correlation_id,
        batch_id=batch_id,
        batch_total=payload.get("batch_total"),
        documents=payload.get("documents", []),
    )
