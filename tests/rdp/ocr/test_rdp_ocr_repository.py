from datetime import timedelta

import pytest
from django.utils import timezone
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation, RdpOperationUnit
from country_workspace.rdp.ocr import repository
from country_workspace.rdp.ocr.types import OcrFindingType


pytestmark = pytest.mark.django_db


def test_ocr_operation_for_rdp(rdp, biometric_operation, ocr_operation: RdpOperation) -> None:
    assert repository.ocr_operation_for_rdp(rdp=rdp) == ocr_operation


def test_ocr_affected_individuals_count(ocr_operation: RdpOperation) -> None:
    from testutils.factories import IndividualFactory, OcrRdpOperationFindingFactory

    individual = IndividualFactory(batch__program=ocr_operation.rdp.program, household=None)
    OcrRdpOperationFindingFactory(
        operation=ocr_operation,
        individual=individual,
        finding_type=OcrFindingType.NO_MATCH.value,
    )
    OcrRdpOperationFindingFactory(
        operation=ocr_operation,
        individual=individual,
        finding_type=OcrFindingType.OCR_ERROR.value,
    )
    OcrRdpOperationFindingFactory(
        operation=ocr_operation,
        finding_type="IGNORED",
    )

    assert repository.ocr_affected_individuals_count(operation=ocr_operation) == 1


def test_create_ocr_units(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    from testutils.factories import IndividualFactory

    individuals = [
        IndividualFactory(batch__program=running_ocr_operation.rdp.program, household=None) for _ in range(2)
    ]
    mocker.patch.object(repository, "lock_current_rdp_operation", return_value=running_ocr_operation)

    assert repository.create_ocr_units(
        operation=running_ocr_operation,
        unit_configs=[
            (individuals[0].pk, {"document_type": "national_id"}),
            (individuals[1].pk, {"document_type": "national_passport"}),
        ],
    )

    assert list(running_ocr_operation.units.order_by("individual_id").values_list("individual_id", "config")) == [
        (individuals[0].pk, {"document_type": "national_id"}),
        (individuals[1].pk, {"document_type": "national_passport"}),
    ]


def test_create_ocr_units_ignores_stale_attempt(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(repository, "lock_current_rdp_operation", return_value=None)

    assert (
        repository.create_ocr_units(
            operation=running_ocr_operation,
            unit_configs=[(1, {"document_type": "national_id"})],
        )
        is False
    )
    assert running_ocr_operation.units.count() == 0


def test_apply_ocr_document_results(
    running_ocr_operation: RdpOperation,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    matched = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    no_match = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    failed = OcrRdpOperationUnitFactory(operation=running_ocr_operation)

    repository.apply_ocr_document_results(
        operation=running_ocr_operation,
        documents=[
            {
                "individual_id": matched.individual_id,
                "status": "ok",
                "found": True,
                "match": ["ID-1", 0.1],
                "error": None,
            },
            {
                "individual_id": no_match.individual_id,
                "status": "ok",
                "found": False,
                "match": None,
                "error": None,
            },
            {
                "individual_id": failed.individual_id,
                "status": "error",
                "found": False,
                "match": None,
                "error": "OCR failed",
            },
        ],
    )

    assert set(running_ocr_operation.units.values_list("status", flat=True)) == {RdpOperationUnit.Status.SUCCESS}

    findings = {
        (finding.individual_id, finding.finding_type): finding for finding in running_ocr_operation.findings.all()
    }
    assert set(findings) == {
        (no_match.individual_id, OcrFindingType.NO_MATCH.value),
        (failed.individual_id, OcrFindingType.OCR_ERROR.value),
    }
    assert findings[(no_match.individual_id, OcrFindingType.NO_MATCH.value)].details == {
        "document_type": no_match.config["document_type"],
    }
    assert findings[(failed.individual_id, OcrFindingType.OCR_ERROR.value)].details == {
        "document_type": failed.config["document_type"],
        "error": "OCR failed",
    }


def test_apply_ocr_document_results_is_idempotent_for_successful_unit(
    ocr_unit: RdpOperationUnit,
) -> None:
    document = {
        "individual_id": ocr_unit.individual_id,
        "status": "ok",
        "found": False,
        "match": None,
        "error": None,
    }
    old_modified = timezone.now() - timedelta(days=1)
    RdpOperationUnit.objects.filter(pk=ocr_unit.pk).update(last_modified=old_modified)

    repository.apply_ocr_document_results(operation=ocr_unit.operation, documents=[document])

    ocr_unit.refresh_from_db()
    first_result_at = ocr_unit.last_modified
    assert first_result_at > old_modified

    repository.apply_ocr_document_results(operation=ocr_unit.operation, documents=[document])

    assert ocr_unit.operation.findings.count() == 1
    ocr_unit.refresh_from_db()
    assert ocr_unit.status == RdpOperationUnit.Status.SUCCESS
    assert ocr_unit.last_modified == first_result_at


def _document(individual_id: int, *, found: bool = False) -> dict[str, object]:
    return {
        "individual_id": individual_id,
        "status": "ok",
        "found": found,
        "match": ["ID-1", 0.0] if found else None,
        "error": None,
    }


def test_apply_ocr_document_results_skips_unknown_individual(
    running_ocr_operation: RdpOperation,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    pending = OcrRdpOperationUnitFactory(operation=running_ocr_operation)

    with caplog.at_level("WARNING"):
        repository.apply_ocr_document_results(
            operation=running_ocr_operation,
            documents=[_document(pending.individual_id), _document(999999)],
        )

    pending.refresh_from_db()
    assert pending.status == RdpOperationUnit.Status.SUCCESS
    assert "999999" in caplog.text
    assert "unknown individual_id" in caplog.text


def test_apply_ocr_document_results_fails_invalid_item_and_saves_valid_results(
    running_ocr_operation: RdpOperation,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    valid = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    invalid = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    reason = "OCR result documents[1]: inconsistent result"

    repository.apply_ocr_document_results(
        operation=running_ocr_operation,
        documents=[_document(valid.individual_id, found=True)],
        issues=[{"individual_id": invalid.individual_id, "reason": reason}],
    )

    valid.refresh_from_db()
    invalid.refresh_from_db()
    assert valid.status == RdpOperationUnit.Status.SUCCESS
    assert valid.error == {}
    assert invalid.status == RdpOperationUnit.Status.FAILURE
    assert invalid.error == {"message": "OCR result is invalid.", "reason": reason}
    assert running_ocr_operation.findings.count() == 0


def test_apply_ocr_document_results_prefers_valid_result_over_invalid_item(
    ocr_unit: RdpOperationUnit,
) -> None:
    repository.apply_ocr_document_results(
        operation=ocr_unit.operation,
        documents=[_document(ocr_unit.individual_id)],
        issues=[{"individual_id": ocr_unit.individual_id, "reason": "duplicate individual_id"}],
    )

    ocr_unit.refresh_from_db()
    assert ocr_unit.status == RdpOperationUnit.Status.SUCCESS
    assert ocr_unit.error == {}


def test_apply_ocr_document_results_skips_missing_individual_id(
    running_ocr_operation: RdpOperation,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    pending = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    applied = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    reason = "OCR result documents[0]: invalid field types"

    with caplog.at_level("WARNING"):
        repository.apply_ocr_document_results(
            operation=running_ocr_operation,
            documents=[_document(applied.individual_id)],
            issues=[{"individual_id": None, "reason": reason}],
        )

    pending.refresh_from_db()
    applied.refresh_from_db()
    assert pending.status == RdpOperationUnit.Status.PENDING
    assert applied.status == RdpOperationUnit.Status.SUCCESS
    assert reason in caplog.text


def test_apply_ocr_document_results_skips_failed_unit(
    running_ocr_operation: RdpOperation,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    failed = OcrRdpOperationUnitFactory(operation=running_ocr_operation, status=RdpOperationUnit.Status.FAILURE)
    other = OcrRdpOperationUnitFactory(operation=running_ocr_operation)

    with caplog.at_level("INFO"):
        repository.apply_ocr_document_results(
            operation=running_ocr_operation,
            documents=[_document(failed.individual_id), _document(other.individual_id)],
        )

    failed.refresh_from_db()
    other.refresh_from_db()
    assert failed.status == RdpOperationUnit.Status.FAILURE
    assert other.status == RdpOperationUnit.Status.SUCCESS
    assert running_ocr_operation.findings.filter(individual_id=other.individual_id).count() == 1
    assert running_ocr_operation.findings.filter(individual_id=failed.individual_id).count() == 0
    assert str(failed.individual_id) in caplog.text
