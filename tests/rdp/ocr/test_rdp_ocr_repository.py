import pytest
from pytest_mock import MockerFixture

from country_workspace.models import RdpOperation, RdpOperationUnit
from country_workspace.rdp.ocr import repository
from country_workspace.rdp.ocr.types import OcrFindingType


pytestmark = pytest.mark.django_db


def test_ocr_operation_for_rdp(rdp, biometric_operation, ocr_operation: RdpOperation) -> None:
    assert repository.ocr_operation_for_rdp(rdp=rdp) == ocr_operation


def test_ocr_finding_counts(ocr_operation: RdpOperation) -> None:
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

    assert repository.ocr_findings_count(operation=ocr_operation) == 2
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

    repository.apply_ocr_document_results(operation=ocr_unit.operation, documents=[document])
    repository.apply_ocr_document_results(operation=ocr_unit.operation, documents=[document])

    assert ocr_unit.operation.findings.count() == 1
    ocr_unit.refresh_from_db()
    assert ocr_unit.status == RdpOperationUnit.Status.SUCCESS


def test_apply_ocr_document_results_rejects_unknown_individual(
    running_ocr_operation: RdpOperation,
) -> None:
    with pytest.raises(ValueError, match="unknown Individual"):
        repository.apply_ocr_document_results(
            operation=running_ocr_operation,
            documents=[
                {
                    "individual_id": 999999,
                    "status": "ok",
                    "found": False,
                    "match": None,
                    "error": None,
                }
            ],
        )


def test_apply_ocr_document_results_rejects_failed_unit(
    ocr_unit: RdpOperationUnit,
) -> None:
    ocr_unit.status = RdpOperationUnit.Status.FAILURE
    ocr_unit.save(update_fields=["status"])

    with pytest.raises(ValueError, match="can not accept"):
        repository.apply_ocr_document_results(
            operation=ocr_unit.operation,
            documents=[
                {
                    "individual_id": ocr_unit.individual_id,
                    "status": "ok",
                    "found": False,
                    "match": None,
                    "error": None,
                }
            ],
        )
