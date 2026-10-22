from decimal import Decimal

from country_workspace.models import Rdp, RdpOperation
from country_workspace.rdp.deduplication.repository import biometric_findings_count, biometric_operation_for_rdp
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.ocr.repository import ocr_findings_count, ocr_operation_for_rdp
from country_workspace.rdp.repository import qs_individuals_for_rdp
from country_workspace.rdp.types import OperationLogResult, ThresholdType


def threshold_exceeded(
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


def _build_threshold_result(
    *,
    operation: RdpOperation,
    findings_count: int,
    total_count: int,
) -> OperationLogResult:
    """Build the review threshold result for an RDP operation."""
    threshold_type = ThresholdType(operation.config["threshold_type"])
    threshold_value = Decimal(str(operation.config["threshold_value"]))
    exceeded = total_count > 0 and threshold_exceeded(
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


def _biometric_threshold_result(*, rdp: Rdp) -> OperationLogResult | None:
    """Return biometric review threshold metrics when configured."""
    if (operation := biometric_operation_for_rdp(rdp=rdp)) is None:
        return None

    total_count = qs_individuals_for_rdp(rdp=rdp).count()
    if not total_count:
        raise RdpWorkflowError({"errors": ["RDP: no individuals available for push."]})

    return _build_threshold_result(
        operation=operation,
        findings_count=biometric_findings_count(operation=operation),
        total_count=total_count,
    )


def _ocr_threshold_result(*, rdp: Rdp) -> OperationLogResult | None:
    """Return OCR review threshold metrics when configured."""
    if (operation := ocr_operation_for_rdp(rdp=rdp)) is None:
        return None

    return _build_threshold_result(
        operation=operation,
        findings_count=ocr_findings_count(operation=operation),
        total_count=operation.units.count(),
    )


def evaluate_review_thresholds(*, rdp: Rdp) -> tuple[OperationLogResult, bool]:
    """Evaluate configured RDP operation review thresholds."""
    thresholds: OperationLogResult = {}
    review_required = False

    for operation_type, result in (
        (RdpOperation.Type.BIOMETRIC_DEDUPLICATION, _biometric_threshold_result(rdp=rdp)),
        (RdpOperation.Type.OCR, _ocr_threshold_result(rdp=rdp)),
    ):
        if result is None:
            continue
        thresholds[operation_type.value] = result
        review_required |= result["threshold_exceeded"] is True

    return thresholds, review_required
