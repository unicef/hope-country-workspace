import pytest

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding, RdpOperationUnit
from country_workspace.rdp.operations.repository import (
    append_rdp_operation_log,
    claim_rdp_operation,
    fail_rdp_operation,
    fail_rdp_operation_units,
    finish_rdp_operation,
    get_rdp_operation,
    get_rdp_operation_units_outcome,
    has_incomplete_rdp_operations,
    prepare_rdp_operation_units_for_retry,
    record_rdp_operation_error,
)


pytestmark = pytest.mark.django_db


def test_get_rdp_operation(biometric_operation: RdpOperation) -> None:
    assert get_rdp_operation(pk=biometric_operation.id) == biometric_operation


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RdpOperation.Status.PENDING, True),
        (RdpOperation.Status.SUCCESS, False),
    ],
)
def test_has_incomplete_rdp_operations(
    biometric_operation: RdpOperation,
    status: RdpOperation.Status,
    expected: bool,
) -> None:
    biometric_operation.status = status
    biometric_operation.save(update_fields=["status"])

    assert has_incomplete_rdp_operations(rdp_id=biometric_operation.rdp_id) is expected


@pytest.mark.parametrize(
    "status",
    [RdpOperation.Status.PENDING, RdpOperation.Status.FAILURE],
)
def test_claim_rdp_operation(
    biometric_operation: RdpOperation,
    status: RdpOperation.Status,
) -> None:
    biometric_operation.status = status
    biometric_operation.attempt = 2
    biometric_operation.error = {"message": "old"}
    biometric_operation.save(update_fields=["status", "attempt", "error"])

    operation = claim_rdp_operation(biometric_operation.id)

    assert operation is not None
    assert operation.status == RdpOperation.Status.RUNNING
    assert operation.attempt == 3
    assert operation.error == {}
    assert operation.started_at is not None
    assert operation.finished_at is None


@pytest.mark.parametrize(
    ("rdp_status", "operation_status"),
    [
        (Rdp.PushStatus.SUCCESS, RdpOperation.Status.PENDING),
        (Rdp.PushStatus.PENDING, RdpOperation.Status.RUNNING),
    ],
    ids=["rdp_not_pending", "operation_not_claimable"],
)
def test_claim_rdp_operation_rejects_invalid_state(
    biometric_operation: RdpOperation,
    rdp_status: Rdp.PushStatus,
    operation_status: RdpOperation.Status,
) -> None:
    rdp = biometric_operation.rdp
    rdp.status = rdp_status
    rdp.save(update_fields=["status"])
    biometric_operation.status = operation_status
    biometric_operation.save(update_fields=["status"])

    assert claim_rdp_operation(biometric_operation.id) is None


def test_fail_rdp_operation(running_biometric_operation: RdpOperation) -> None:
    error = {"message": "failed"}

    assert (
        fail_rdp_operation(
            operation_id=running_biometric_operation.id,
            error=error,
        )
        is True
    )

    running_biometric_operation.refresh_from_db()
    assert running_biometric_operation.status == RdpOperation.Status.FAILURE
    assert running_biometric_operation.error == error
    assert running_biometric_operation.finished_at is not None


def test_fail_rdp_operation_ignores_non_running(
    biometric_operation: RdpOperation,
) -> None:
    assert (
        fail_rdp_operation(
            operation_id=biometric_operation.id,
            error={"message": "failed"},
        )
        is False
    )


def test_finish_rdp_operation(
    running_biometric_operation: RdpOperation,
) -> None:
    from testutils.factories import BiometricRdpOperationFindingFactory, IndividualFactory

    old_finding = BiometricRdpOperationFindingFactory(operation=running_biometric_operation)
    individual = IndividualFactory(batch__program=running_biometric_operation.rdp.program)
    finding = RdpOperationFinding(
        finding_type=FindingStatusCode.BAD_IMAGE_QUALITY.name,
        individual=individual,
        field_name="photo",
    )

    assert (
        finish_rdp_operation(
            operation_id=running_biometric_operation.id,
            findings=[finding],
        )
        is True
    )

    running_biometric_operation.refresh_from_db()
    assert running_biometric_operation.status == RdpOperation.Status.SUCCESS
    assert running_biometric_operation.error == {}
    assert running_biometric_operation.finished_at is not None
    assert not RdpOperationFinding.objects.filter(pk=old_finding.pk).exists()

    saved = running_biometric_operation.findings.get()
    assert saved.individual == individual
    assert saved.finding_type == FindingStatusCode.BAD_IMAGE_QUALITY.name


def test_finish_rdp_operation_ignores_non_running(
    biometric_operation: RdpOperation,
) -> None:
    assert (
        finish_rdp_operation(
            operation_id=biometric_operation.id,
            findings=[],
        )
        is False
    )


@pytest.mark.parametrize(
    "result",
    [None, {"success": True}],
    ids=["without_result", "with_result"],
)
def test_append_rdp_operation_log(
    biometric_operation: RdpOperation,
    result,
) -> None:
    biometric_operation.log = [{"action": "EXISTING"}]
    biometric_operation.save(update_fields=["log"])

    append_rdp_operation_log(
        operation_id=biometric_operation.id,
        action="TEST",
        result=result,
    )

    biometric_operation.refresh_from_db()

    assert biometric_operation.log[0] == {"action": "EXISTING"}
    entry = biometric_operation.log[1]
    assert entry["action"] == "TEST"
    assert "timestamp" in entry
    if result is None:
        assert "result" not in entry
    else:
        assert entry["result"] == result


@pytest.mark.parametrize(
    ("attempt_offset", "expected", "retry_status"),
    [
        (0, True, RdpOperationUnit.Status.PENDING),
        (1, False, RdpOperationUnit.Status.FAILURE),
    ],
    ids=["current", "stale"],
)
def test_prepare_rdp_operation_units_for_retry(
    running_ocr_operation: RdpOperation,
    attempt_offset: int,
    expected: bool,
    retry_status: RdpOperationUnit.Status,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    success = OcrRdpOperationUnitFactory(operation=running_ocr_operation, status=RdpOperationUnit.Status.SUCCESS)
    retry = OcrRdpOperationUnitFactory(operation=running_ocr_operation, status=RdpOperationUnit.Status.FAILURE)

    assert (
        prepare_rdp_operation_units_for_retry(
            operation_id=running_ocr_operation.id,
            expected_attempt=running_ocr_operation.attempt + attempt_offset,
        )
        is expected
    )

    success.refresh_from_db()
    retry.refresh_from_db()
    assert success.status == RdpOperationUnit.Status.SUCCESS
    assert retry.status == retry_status


@pytest.mark.parametrize(("attempt_offset", "expected"), [(0, 1), (1, 0)], ids=["current", "stale"])
def test_fail_rdp_operation_units(
    running_ocr_operation: RdpOperation,
    attempt_offset: int,
    expected: int,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    pending = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    success = OcrRdpOperationUnitFactory(operation=running_ocr_operation, status=RdpOperationUnit.Status.SUCCESS)
    other = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    error = {"message": "failed"}

    assert (
        fail_rdp_operation_units(
            operation_id=running_ocr_operation.id,
            expected_attempt=running_ocr_operation.attempt + attempt_offset,
            unit_ids=[pending.pk, success.pk],
            error=error,
        )
        == expected
    )

    pending.refresh_from_db()
    success.refresh_from_db()
    other.refresh_from_db()
    assert pending.status == (RdpOperationUnit.Status.FAILURE if expected else RdpOperationUnit.Status.PENDING)
    assert pending.error == (error if expected else {})
    assert success.status == RdpOperationUnit.Status.SUCCESS
    assert other.status == RdpOperationUnit.Status.PENDING


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], None),
        ([RdpOperationUnit.Status.PENDING], None),
        ([RdpOperationUnit.Status.SUCCESS], RdpOperation.Status.SUCCESS),
        ([RdpOperationUnit.Status.SUCCESS, RdpOperationUnit.Status.FAILURE], RdpOperation.Status.FAILURE),
    ],
    ids=["empty", "pending", "success", "failure"],
)
def test_get_rdp_operation_units_outcome(
    running_ocr_operation: RdpOperation,
    statuses: list[RdpOperationUnit.Status],
    expected: RdpOperation.Status | None,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    for status in statuses:
        OcrRdpOperationUnitFactory(operation=running_ocr_operation, status=status)

    assert get_rdp_operation_units_outcome(operation_id=running_ocr_operation.id) == expected


@pytest.mark.parametrize(
    ("with_pending", "expected_status"),
    [
        (True, RdpOperation.Status.RUNNING),
        (False, RdpOperation.Status.FAILURE),
    ],
)
def test_record_rdp_operation_error(
    running_ocr_operation: RdpOperation,
    with_pending: bool,
    expected_status: RdpOperation.Status,
) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    if with_pending:
        OcrRdpOperationUnitFactory(operation=running_ocr_operation)

    error = {"message": "failed"}
    assert record_rdp_operation_error(
        operation_id=running_ocr_operation.id,
        expected_attempt=running_ocr_operation.attempt,
        error=error,
    )

    running_ocr_operation.refresh_from_db()
    assert running_ocr_operation.status == expected_status
    assert running_ocr_operation.error == error
    assert running_ocr_operation.log[-1]["action"] == "EXECUTION_ERROR"
    assert (running_ocr_operation.finished_at is None) is with_pending


def test_record_rdp_operation_error_ignores_stale_attempt(running_ocr_operation: RdpOperation) -> None:
    assert (
        record_rdp_operation_error(
            operation_id=running_ocr_operation.id,
            expected_attempt=running_ocr_operation.attempt + 1,
            error={"message": "failed"},
        )
        is False
    )

    running_ocr_operation.refresh_from_db()
    assert running_ocr_operation.status == RdpOperation.Status.RUNNING
