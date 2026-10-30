from itertools import batched
from uuid import UUID

from django.db import transaction

from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding, RdpOperationUnit
from country_workspace.rdp.operations.repository import lock_current_rdp_operation

from .constants import OCR_AFFECTING_FINDING_TYPES, OCR_UNIT_BULK_CREATE_BATCH_SIZE
from .types import OcrDocumentResult, OcrFindingType, OcrUnitConfig


def ocr_operation_for_rdp(*, rdp: Rdp) -> RdpOperation | None:
    """Return the OCR operation for an RDP."""
    return rdp.operations.filter(operation_type=RdpOperation.Type.OCR).first()


def ocr_affected_individuals_count(*, operation: RdpOperation) -> int:
    """Return the number of individuals affected by OCR findings."""
    return (
        operation.findings.filter(finding_type__in=OCR_AFFECTING_FINDING_TYPES)
        .values("individual_id")
        .distinct()
        .count()
    )


def lock_ocr_operation_for_update(*, rdp_id: int) -> RdpOperation | None:
    """Return the OCR operation locked for update."""
    try:
        return RdpOperation.objects.select_for_update().get(
            rdp_id=rdp_id,
            operation_type=RdpOperation.Type.OCR,
        )
    except RdpOperation.DoesNotExist:
        return None


def lock_ocr_units_for_update(
    *,
    operation_id: UUID,
    individual_ids: set[int],
) -> dict[int, RdpOperationUnit]:
    """Return OCR operation units locked by individual ID."""
    return {
        unit.individual_id: unit
        for unit in (
            RdpOperationUnit.objects.select_for_update()
            .filter(operation_id=operation_id, individual_id__in=individual_ids)
            .order_by("pk")
        )
    }


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


def _build_ocr_finding(
    *,
    operation: RdpOperation,
    unit: RdpOperationUnit,
    result: OcrDocumentResult,
) -> RdpOperationFinding | None:
    """Build an adverse OCR finding."""
    if result["found"]:
        return None

    details = {"document_type": unit.config["document_type"]}
    if result["error"] is not None:
        details["error"] = result["error"]

    return RdpOperationFinding(
        operation=operation,
        individual_id=unit.individual_id,
        finding_type=(OcrFindingType.OCR_ERROR.value if result["status"] == "error" else OcrFindingType.NO_MATCH.value),
        details=details,
    )


def apply_ocr_document_results(
    *,
    operation: RdpOperation,
    documents: list[OcrDocumentResult],
) -> None:
    """Apply validated OCR document results."""
    individual_ids = {result["individual_id"] for result in documents}

    with transaction.atomic():
        units = lock_ocr_units_for_update(operation_id=operation.id, individual_ids=individual_ids)

        if missing := individual_ids.difference(units):
            raise ValueError(f"OCR result contains unknown Individual IDs: {', '.join(map(str, sorted(missing)))}")

        processed_unit_ids: list[int] = []
        findings: list[RdpOperationFinding] = []

        for result in documents:
            unit = units[result["individual_id"]]
            if unit.status == RdpOperationUnit.Status.SUCCESS:
                continue
            if unit.status != RdpOperationUnit.Status.PENDING:
                raise ValueError(
                    f"OCR unit for Individual {unit.individual_id} can not accept a result in status={unit.status}"
                )

            processed_unit_ids.append(unit.pk)
            if finding := _build_ocr_finding(operation=operation, unit=unit, result=result):
                findings.append(finding)

        if findings:
            RdpOperationFinding.objects.bulk_create(findings)
        if processed_unit_ids:
            RdpOperationUnit.objects.filter(pk__in=processed_unit_ids).update(
                status=RdpOperationUnit.Status.SUCCESS,
                error={},
            )
