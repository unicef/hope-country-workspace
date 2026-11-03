from decimal import Decimal
from typing import cast

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Rdp, RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.push import thresholds
from country_workspace.rdp.types import ThresholdType


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("findings_count", "total_count", "threshold_type", "threshold_value", "expected"),
    [
        (2, 10, ThresholdType.COUNT, Decimal(1), True),
        (1, 10, ThresholdType.COUNT, Decimal(1), False),
        (2, 4, ThresholdType.RATE, Decimal(49), True),
        (2, 4, ThresholdType.RATE, Decimal(50), False),
    ],
)
def test_threshold_exceeded(
    findings_count: int,
    total_count: int,
    threshold_type: ThresholdType,
    threshold_value: Decimal,
    expected: bool,
) -> None:
    assert (
        thresholds._threshold_exceeded(
            findings_count=findings_count,
            total_count=total_count,
            threshold_type=threshold_type,
            threshold_value=threshold_value,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("findings_count", "total_count", "threshold_type", "threshold_value"),
    [
        (-1, 1, ThresholdType.COUNT, Decimal(0)),
        (0, 0, ThresholdType.COUNT, Decimal(0)),
        (0, 1, ThresholdType.COUNT, Decimal(-1)),
        (0, 1, cast("ThresholdType", "invalid"), Decimal(0)),
    ],
)
def test_threshold_exceeded_rejects_invalid_input(
    findings_count: int,
    total_count: int,
    threshold_type: ThresholdType,
    threshold_value: Decimal,
) -> None:
    with pytest.raises(ValueError, match="Invalid"):
        thresholds._threshold_exceeded(
            findings_count=findings_count,
            total_count=total_count,
            threshold_type=threshold_type,
            threshold_value=threshold_value,
        )


def test_evaluate_review_thresholds_requires_biometric_individuals(
    successful_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    individuals = mocker.patch.object(thresholds, "qs_individuals_for_rdp")
    individuals.return_value.count.return_value = 0

    with pytest.raises(RdpWorkflowError, match="no individuals"):
        thresholds.evaluate_review_thresholds(rdp=successful_biometric_operation.rdp)


def test_ocr_threshold_uses_operation_units(
    successful_ocr_operation: RdpOperation,
) -> None:
    from testutils.factories import OcrRdpOperationFindingFactory, OcrRdpOperationUnitFactory

    successful_ocr_operation.config = {
        "threshold_type": ThresholdType.RATE.value,
        "threshold_value": "49",
    }
    successful_ocr_operation.save(update_fields=["config"])
    OcrRdpOperationUnitFactory.create_batch(4, operation=successful_ocr_operation)
    OcrRdpOperationFindingFactory.create_batch(2, operation=successful_ocr_operation)

    result, review_required = thresholds.evaluate_review_thresholds(rdp=successful_ocr_operation.rdp)

    assert result[RdpOperation.Type.OCR.value] == {
        "threshold_type": ThresholdType.RATE.value,
        "threshold_value": "49",
        "findings_count": 2,
        "total_count": 4,
        "findings_rate": "50.00",
        "threshold_exceeded": True,
    }
    assert review_required is True


def test_ocr_threshold_with_no_units(
    successful_ocr_operation: RdpOperation,
) -> None:
    successful_ocr_operation.config = {
        "threshold_type": ThresholdType.RATE.value,
        "threshold_value": "0",
    }
    successful_ocr_operation.save(update_fields=["config"])

    result, review_required = thresholds.evaluate_review_thresholds(rdp=successful_ocr_operation.rdp)

    assert result[RdpOperation.Type.OCR.value] == {
        "threshold_type": ThresholdType.RATE.value,
        "threshold_value": "0",
        "findings_count": 0,
        "total_count": 0,
        "findings_rate": None,
        "threshold_exceeded": False,
    }
    assert review_required is False


def test_evaluate_review_thresholds_without_operations(rdp: Rdp) -> None:
    assert thresholds.evaluate_review_thresholds(rdp=rdp) == ({}, False)


def test_evaluate_review_thresholds_combines_operations(
    rdp: Rdp,
    successful_biometric_operation: RdpOperation,
    successful_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    from testutils.factories import (
        BiometricRdpOperationFindingFactory,
        OcrRdpOperationFindingFactory,
        OcrRdpOperationUnitFactory,
    )

    successful_biometric_operation.config = {
        "threshold_type": ThresholdType.COUNT.value,
        "threshold_value": "1",
    }
    successful_biometric_operation.save(update_fields=["config"])
    successful_ocr_operation.config = {
        "threshold_type": ThresholdType.COUNT.value,
        "threshold_value": "1",
    }
    successful_ocr_operation.save(update_fields=["config"])

    BiometricRdpOperationFindingFactory(operation=successful_biometric_operation)
    OcrRdpOperationFindingFactory.create_batch(2, operation=successful_ocr_operation)
    OcrRdpOperationUnitFactory.create_batch(2, operation=successful_ocr_operation)

    individuals = mocker.patch.object(thresholds, "qs_individuals_for_rdp")
    individuals.return_value.count.return_value = 10

    result, review_required = thresholds.evaluate_review_thresholds(rdp=rdp)

    assert set(result) == {
        RdpOperation.Type.BIOMETRIC_DEDUPLICATION.value,
        RdpOperation.Type.OCR.value,
    }
    assert result[RdpOperation.Type.BIOMETRIC_DEDUPLICATION.value]["threshold_exceeded"] is False
    assert result[RdpOperation.Type.OCR.value]["threshold_exceeded"] is True
    assert review_required is True
