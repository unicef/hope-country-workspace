import pytest

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp.operations.repository import (
    append_rdp_operation_log,
    claim_rdp_operation,
    fail_rdp_operation,
    failed_rdp_operations,
    finish_rdp_operation,
    get_rdp_operation,
    has_incomplete_rdp_operations,
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


def test_failed_rdp_operations(
    failed_biometric_operation: RdpOperation,
) -> None:
    assert list(failed_rdp_operations(rdp_id=failed_biometric_operation.rdp_id)) == [failed_biometric_operation]


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
