import logging
from dataclasses import dataclass
from itertools import batched
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding, RdpOperationUnit
from country_workspace.rdp.operations.repository import lock_current_rdp_operation

from .constants import OCR_AFFECTING_FINDING_TYPES, OCR_UNIT_BULK_CREATE_BATCH_SIZE
from .types import OcrDocumentIssue, OcrDocumentResult, OcrFindingType, OcrUnitConfig

logger = logging.getLogger(__name__)


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


def _ocr_result_individual_ids(
    documents: list[OcrDocumentResult],
    issues: list[OcrDocumentIssue],
) -> set[int]:
    """Return every individual id carried by applicable results or item problems."""
    individual_ids = {result["individual_id"] for result in documents}
    individual_ids.update(issue["individual_id"] for issue in issues if issue["individual_id"] is not None)
    return individual_ids


@dataclass(slots=True)
class _OcrSkipLog:
    valid_ids: set[int]
    unknown: set[int]
    terminal: set[int]

    def claim(self, seen: set[int], individual_id: int) -> bool:
        """Return whether this individual id has not been logged yet."""
        if individual_id in seen:
            return False
        seen.add(individual_id)
        return True


def _log_ocr_issue(
    *,
    operation: RdpOperation,
    issue: OcrDocumentIssue,
    units: dict[int, RdpOperationUnit],
    seen: _OcrSkipLog,
) -> None:
    """Log one result item that is not applied on its own."""
    individual_id = issue["individual_id"]
    if individual_id is None:
        logger.warning("OCR result item skipped operation=%s reason=%s", operation.id, issue["reason"])
        return

    unit = units.get(individual_id)
    if unit is None:
        if seen.claim(seen.unknown, individual_id):
            logger.warning(
                "OCR result item skipped operation=%s individual_id=%s reason=%s",
                operation.id,
                individual_id,
                issue["reason"],
            )
        return
    if individual_id in seen.valid_ids:
        logger.info(
            "OCR result item skipped operation=%s individual_id=%s reason=%s",
            operation.id,
            individual_id,
            issue["reason"],
        )
        return
    if unit.status != RdpOperationUnit.Status.PENDING and seen.claim(seen.terminal, individual_id):
        logger.info(
            "OCR result item skipped operation=%s individual_id=%s status=%s",
            operation.id,
            individual_id,
            unit.status,
        )


def _log_unresolved_ocr_items(
    *,
    operation: RdpOperation,
    documents: list[OcrDocumentResult],
    issues: list[OcrDocumentIssue],
    units: dict[int, RdpOperationUnit],
) -> None:
    """Log result items that cannot be matched to a pending unit."""
    seen = _OcrSkipLog(
        valid_ids={result["individual_id"] for result in documents if result["individual_id"] in units},
        unknown=set(),
        terminal=set(),
    )
    for issue in issues:
        _log_ocr_issue(operation=operation, issue=issue, units=units, seen=seen)

    for result in documents:
        individual_id = result["individual_id"]
        unit = units.get(individual_id)
        if unit is None and seen.claim(seen.unknown, individual_id):
            logger.warning(
                "OCR result item skipped operation=%s individual_id=%s reason=unknown individual_id",
                operation.id,
                individual_id,
            )
        elif (
            unit is not None
            and unit.status == RdpOperationUnit.Status.FAILURE
            and seen.claim(seen.terminal, individual_id)
        ):
            logger.info(
                "OCR result item skipped operation=%s individual_id=%s status=%s",
                operation.id,
                individual_id,
                unit.status,
            )


def _failure_reasons_for_invalid_results(
    *,
    operation: RdpOperation,
    documents: list[OcrDocumentResult],
    issues: list[OcrDocumentIssue],
    units: dict[int, RdpOperationUnit],
) -> dict[int, str]:
    """Return pending units whose only result is invalid, keyed by unit pk."""
    valid_ids = {result["individual_id"] for result in documents if result["individual_id"] in units}
    reasons: dict[int, str] = {}
    for issue in issues:
        individual_id = issue["individual_id"]
        unit = None if individual_id is None else units.get(individual_id)
        if (
            unit is None
            or individual_id in valid_ids
            or unit.status != RdpOperationUnit.Status.PENDING
            or unit.pk in reasons
        ):
            continue
        reasons[unit.pk] = issue["reason"]
        logger.warning(
            "OCR result marked unit failure operation=%s individual_id=%s reason=%s",
            operation.id,
            individual_id,
            issue["reason"],
        )
    return reasons


def _store_ocr_unit_outcomes(
    *,
    findings: list[RdpOperationFinding],
    processed_unit_ids: list[int],
    failed_reasons: dict[int, str],
) -> None:
    """Persist successful OCR results and invalid-result failures."""
    if findings:
        RdpOperationFinding.objects.bulk_create(findings)
    now = timezone.now()
    if processed_unit_ids:
        RdpOperationUnit.objects.filter(pk__in=processed_unit_ids).update(
            status=RdpOperationUnit.Status.SUCCESS,
            error={},
            last_modified=now,
        )
    for unit_id, reason in failed_reasons.items():
        RdpOperationUnit.objects.filter(pk=unit_id).update(
            status=RdpOperationUnit.Status.FAILURE,
            error={"message": "OCR result is invalid.", "reason": reason},
            last_modified=now,
        )


def apply_ocr_document_results(
    *,
    operation: RdpOperation,
    documents: list[OcrDocumentResult],
    issues: list[OcrDocumentIssue] | None = None,
) -> None:
    """Apply OCR document results, isolating items that cannot be applied.

    A valid result for a pending unit is stored. An invalid result for a known
    pending unit marks that unit FAILURE. Unknown or missing individual ids are
    skipped, and units that are already SUCCESS or FAILURE stay unchanged.
    """
    item_issues = list(issues or [])
    with transaction.atomic():
        units = lock_ocr_units_for_update(
            operation_id=operation.id,
            individual_ids=_ocr_result_individual_ids(documents, item_issues),
        )
        _log_unresolved_ocr_items(operation=operation, documents=documents, issues=item_issues, units=units)
        failed_reasons = _failure_reasons_for_invalid_results(
            operation=operation,
            documents=documents,
            issues=item_issues,
            units=units,
        )

        processed_unit_ids: list[int] = []
        findings: list[RdpOperationFinding] = []
        for result in documents:
            unit = units.get(result["individual_id"])
            if unit is None or unit.status != RdpOperationUnit.Status.PENDING:
                continue
            processed_unit_ids.append(unit.pk)
            if finding := _build_ocr_finding(operation=operation, unit=unit, result=result):
                findings.append(finding)

        _store_ocr_unit_outcomes(
            findings=findings,
            processed_unit_ids=processed_unit_ids,
            failed_reasons=failed_reasons,
        )
