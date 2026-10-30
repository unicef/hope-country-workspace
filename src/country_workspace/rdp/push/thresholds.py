from decimal import Decimal

from django.db.models import Q, QuerySet

from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp.deduplication.constants import BIOMETRIC_AFFECTING_FINDING_TYPES
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.ocr.constants import OCR_AFFECTING_FINDING_TYPES
from country_workspace.rdp.repository import (
    qs_individuals_by_household_pks,
    qs_individuals_by_pks,
    qs_individuals_for_rdp,
)
from country_workspace.rdp.types import OperationLogResult, ThresholdType


def _threshold_exceeded(
    *,
    findings_count: int,
    total_count: int,
    threshold_type: ThresholdType,
    threshold_value: Decimal,
) -> bool:
    """Check whether findings exceed the selected threshold."""
    if findings_count < 0 or total_count <= 0 or threshold_value < 0:
        raise ValueError("Invalid threshold inputs.")

    if threshold_type == ThresholdType.COUNT:
        return Decimal(findings_count) > threshold_value
    if threshold_type == ThresholdType.RATE:
        return Decimal(findings_count) * 100 > threshold_value * total_count
    raise ValueError(f"Invalid threshold type: {threshold_type}")


def _threshold_findings(operation: RdpOperation) -> QuerySet[RdpOperationFinding] | None:
    """Return findings affecting review for a supported RDP operation."""
    match operation.operation_type:
        case RdpOperation.Type.BIOMETRIC_DEDUPLICATION:
            finding_types = BIOMETRIC_AFFECTING_FINDING_TYPES
        case RdpOperation.Type.OCR:
            finding_types = OCR_AFFECTING_FINDING_TYPES
        case _:
            return None
    return operation.findings.filter(finding_type__in=finding_types)


def _threshold_total_count(operation: RdpOperation) -> int | None:
    """Return the threshold denominator for a supported RDP operation."""
    match operation.operation_type:
        case RdpOperation.Type.BIOMETRIC_DEDUPLICATION:
            if not (total_count := qs_individuals_for_rdp(rdp=operation.rdp).count()):
                raise RdpWorkflowError({"errors": ["RDP: no individuals available for push."]})
            return total_count
        case RdpOperation.Type.OCR:
            return operation.units.count()
        case _:
            return None


def _build_threshold_result(
    *,
    operation: RdpOperation,
    findings_count: int,
    total_count: int,
) -> OperationLogResult:
    """Build the review threshold result for an RDP operation."""
    threshold_type = ThresholdType(operation.config["threshold_type"])
    threshold_value = Decimal(str(operation.config["threshold_value"]))
    exceeded = total_count > 0 and _threshold_exceeded(
        findings_count=findings_count,
        total_count=total_count,
        threshold_type=threshold_type,
        threshold_value=threshold_value,
    )

    return {
        "threshold_type": threshold_type.value,
        "threshold_value": str(threshold_value),
        "findings_count": findings_count,
        "total_count": total_count,
        "findings_rate": f"{Decimal(findings_count) * 100 / total_count:.2f}" if total_count else None,
        "threshold_exceeded": exceeded,
    }


def _operation_threshold_result(operation: RdpOperation) -> OperationLogResult | None:
    """Return review threshold metrics for a supported RDP operation."""
    findings = _threshold_findings(operation)
    total_count = _threshold_total_count(operation)
    if findings is None or total_count is None:
        return None
    return _build_threshold_result(
        operation=operation,
        findings_count=findings.count(),
        total_count=total_count,
    )


def _operation_threshold_results(*, rdp: Rdp) -> list[tuple[RdpOperation, OperationLogResult]]:
    """Return review threshold metrics for configured RDP operations."""
    return [
        (operation, result)
        for operation in rdp.operations.order_by("operation_type")
        if (result := _operation_threshold_result(operation)) is not None
    ]


def exceeded_operation_thresholds(*, rdp: Rdp) -> list[tuple[RdpOperation, OperationLogResult]]:
    """Return RDP operations whose review thresholds are exceeded."""
    return [
        (operation, result)
        for operation, result in _operation_threshold_results(rdp=rdp)
        if result["threshold_exceeded"] is True
    ]


def threshold_findings_count_for_selection(
    *,
    operation: RdpOperation,
    master_detail: bool,
    pks: list[int],
) -> int:
    """Return affecting findings that still apply to a beneficiary selection."""
    if (findings := _threshold_findings(operation)) is None:
        raise ValueError(f"Unsupported RDP operation type: {operation.operation_type}")

    remaining = qs_individuals_by_household_pks(pks) if master_detail else qs_individuals_by_pks(pks)
    current = qs_individuals_for_rdp(rdp=operation.rdp)
    remaining_ids = remaining.values("pk")
    current_ids = current.values("pk")

    return (
        findings.filter(individual_id__in=remaining_ids)
        .filter(
            Q(related_individual_id__isnull=True)
            | ~Q(related_individual_id__in=current_ids)
            | Q(related_individual_id__in=remaining_ids)
        )
        .count()
    )


def evaluate_review_thresholds(*, rdp: Rdp) -> tuple[OperationLogResult, bool]:
    """Evaluate configured RDP operation review thresholds."""
    results = _operation_threshold_results(rdp=rdp)
    return (
        {operation.operation_type: result for operation, result in results},
        any(result["threshold_exceeded"] is True for _, result in results),
    )
