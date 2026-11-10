import pytest

from country_workspace.contrib.dedup_engine import FindingStatusCode
from country_workspace.models import Rdp, RdpOperation, RdpOperationFinding, RdpOperationUnit
from country_workspace.rdp.operations.repository import (
    RdpOperationFindingsSummary,
    append_rdp_operation_log,
    claim_rdp_operation,
    fail_rdp_operation,
    fail_rdp_operation_units,
    finish_rdp_operation,
    get_rdp_operation,
    get_rdp_operation_units_outcome,
    has_incomplete_rdp_operations,
    has_rdp_operation_units,
    latest_operation_findings_by_individual,
    pending_rdp_operation_units,
    prepare_rdp_operation_units_for_retry,
    qs_individuals_with_latest_operation_findings,
    qs_individuals_with_rdp_findings,
    qs_rdp_operation_findings,
    record_rdp_operation_error,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def duplicate(successful_biometric_operation: RdpOperation) -> RdpOperationFinding:
    from testutils.factories import BiometricRdpOperationFindingFactory, HouseholdFactory, IndividualFactory

    rdp = successful_biometric_operation.rdp
    rdp.status = Rdp.PushStatus.SUCCESS
    rdp.save(update_fields=["status"])
    households = HouseholdFactory.create_batch(2, batch__program=rdp.program, individuals=[])
    members = [IndividualFactory(household=household) for household in reversed(households)]
    return BiometricRdpOperationFindingFactory(
        operation=successful_biometric_operation,
        finding_type=FindingStatusCode.DUPLICATE.name,
        individual=members[0],
        related_individual=members[1],
    )


@pytest.fixture
def operation_findings(
    duplicate: RdpOperationFinding,
    successful_ocr_operation: RdpOperation,
) -> tuple[RdpOperationFinding, RdpOperationFinding, RdpOperationFinding]:
    from testutils.factories import BiometricRdpOperationFindingFactory, OcrRdpOperationFindingFactory

    return (
        duplicate,
        BiometricRdpOperationFindingFactory(operation=duplicate.operation, individual=duplicate.individual),
        OcrRdpOperationFindingFactory(operation=successful_ocr_operation, individual=duplicate.individual),
    )


@pytest.mark.parametrize("field", ["individual_id", "household_id"])
def test_qs_rdp_operation_findings_includes_both_sides(
    operation_findings: tuple[RdpOperationFinding, RdpOperationFinding, RdpOperationFinding],
    field: str,
) -> None:
    duplicate, issue, _ = operation_findings
    primary, related = duplicate.individual, duplicate.related_individual
    primary_id = primary.pk if field == "individual_id" else primary.household_id
    related_id = related.pk if field == "individual_id" else related.household_id

    assert set(qs_rdp_operation_findings(operation=duplicate.operation, **{field: primary_id})) == {duplicate, issue}
    assert list(qs_rdp_operation_findings(operation=duplicate.operation, **{field: related_id})) == [duplicate]


def test_qs_individuals_with_rdp_findings_is_scoped(
    operation_findings: tuple[RdpOperationFinding, RdpOperationFinding, RdpOperationFinding],
) -> None:
    from testutils.factories import BiometricRdpOperationFindingFactory, IndividualFactory

    duplicate, _, _ = operation_findings
    rdp = duplicate.operation.rdp
    BiometricRdpOperationFindingFactory(operation=duplicate.operation, individual=IndividualFactory(household=None))
    BiometricRdpOperationFindingFactory(
        operation__rdp__program=rdp.program,
        operation__rdp__status=Rdp.PushStatus.SUCCESS,
    )

    result = qs_individuals_with_rdp_findings(rdp=rdp)
    expected = sorted([duplicate.individual_id, duplicate.related_individual_id])
    assert sorted(result.values_list("pk", flat=True)) == expected


def test_latest_operation_findings_by_individual(
    operation_findings: tuple[RdpOperationFinding, RdpOperationFinding, RdpOperationFinding],
) -> None:
    duplicate, issue, ocr = operation_findings
    program = duplicate.operation.rdp.program
    expected = {
        duplicate.individual_id: [
            RdpOperationFindingsSummary(duplicate.operation, frozenset({duplicate.pk, issue.pk})),
            RdpOperationFindingsSummary(ocr.operation, frozenset({ocr.pk})),
        ],
        duplicate.related_individual_id: [RdpOperationFindingsSummary(duplicate.operation, frozenset({duplicate.pk}))],
    }

    assert latest_operation_findings_by_individual(program=program, individual_ids=expected) == expected
    result = qs_individuals_with_latest_operation_findings(program=program)
    assert sorted(result.values_list("pk", flat=True)) == sorted(expected)


@pytest.mark.parametrize("master_detail", [True, False], ids=["households", "people"])
def test_latest_clean_biometric_operation_clears_only_members_findings(
    duplicate: RdpOperationFinding,
    master_detail: bool,
) -> None:
    from testutils.factories import BiometricRdpOperationFactory, RdpFactory

    rdp = duplicate.operation.rdp
    program = rdp.program
    program.beneficiary_group.master_detail = master_detail
    program.beneficiary_group.save(update_fields=["master_detail"])
    newer = RdpFactory(program=program, status=Rdp.PushStatus.SUCCESS)
    Rdp.objects.filter(pk=newer.pk).update(push_date=rdp.push_date)
    BiometricRdpOperationFactory(rdp=newer, status=RdpOperation.Status.SUCCESS)
    if master_detail:
        newer.households.add(duplicate.individual.household)
    else:
        newer.individuals.add(duplicate.individual)

    expected = {
        duplicate.related_individual_id: [RdpOperationFindingsSummary(duplicate.operation, frozenset({duplicate.pk}))],
    }
    assert (
        latest_operation_findings_by_individual(
            program=program, individual_ids=[duplicate.individual_id, duplicate.related_individual_id]
        )
        == expected
    )
    assert list(qs_individuals_with_latest_operation_findings(program=program)) == [duplicate.related_individual]


@pytest.mark.parametrize("with_unit", [True, False], ids=["processed", "not-processed"])
def test_latest_clean_ocr_operation_requires_individual_unit(
    successful_ocr_operation: RdpOperation,
    with_unit: bool,
) -> None:
    from testutils.factories import (
        OcrRdpOperationFactory,
        OcrRdpOperationFindingFactory,
        OcrRdpOperationUnitFactory,
        RdpFactory,
    )

    rdp = successful_ocr_operation.rdp
    rdp.program.beneficiary_group.master_detail = False
    rdp.program.beneficiary_group.save(update_fields=["master_detail"])
    finding = OcrRdpOperationFindingFactory(operation=successful_ocr_operation)
    newer = RdpFactory(program=rdp.program, status=Rdp.PushStatus.SUCCESS)
    newer.individuals.add(finding.individual)
    operation = OcrRdpOperationFactory(rdp=newer, status=RdpOperation.Status.SUCCESS)
    if with_unit:
        OcrRdpOperationUnitFactory(
            operation=operation, individual=finding.individual, status=RdpOperationUnit.Status.SUCCESS
        )

    expected = (
        {}
        if with_unit
        else {finding.individual_id: [RdpOperationFindingsSummary(successful_ocr_operation, frozenset({finding.pk}))]}
    )
    assert (
        latest_operation_findings_by_individual(program=rdp.program, individual_ids=[finding.individual_id]) == expected
    )
    assert list(qs_individuals_with_latest_operation_findings(program=rdp.program)) == (
        [] if with_unit else [finding.individual]
    )


@pytest.mark.parametrize(
    ("operation_status", "rdp_status"),
    [
        (RdpOperation.Status.FAILURE, Rdp.PushStatus.PENDING),
        (RdpOperation.Status.SUCCESS, Rdp.PushStatus.CANCELLED),
    ],
    ids=["unsuccessful", "cancelled"],
)
def test_latest_operation_findings_ignore_unsuccessful_and_cancelled_history(
    duplicate: RdpOperationFinding,
    operation_status: RdpOperation.Status,
    rdp_status: Rdp.PushStatus,
) -> None:
    from testutils.factories import BiometricRdpOperationFactory, RdpFactory

    rdp = duplicate.operation.rdp
    program = rdp.program
    program.beneficiary_group.master_detail = True
    program.beneficiary_group.save(update_fields=["master_detail"])
    newer = RdpFactory(program=program, status=rdp_status)
    newer.households.add(duplicate.individual.household)
    BiometricRdpOperationFactory(rdp=newer, status=operation_status)

    assert latest_operation_findings_by_individual(program=program, individual_ids=[duplicate.individual_id]) == {
        duplicate.individual_id: [RdpOperationFindingsSummary(duplicate.operation, frozenset({duplicate.pk}))],
    }
    assert set(qs_individuals_with_latest_operation_findings(program=program)) == {
        duplicate.individual,
        duplicate.related_individual,
    }


def test_latest_operation_findings_exclude_other_programs(duplicate: RdpOperationFinding) -> None:
    from testutils.factories import BiometricRdpOperationFindingFactory, IndividualFactory

    individual = IndividualFactory(household=None)
    program = individual.batch.program
    BiometricRdpOperationFindingFactory(operation=duplicate.operation, individual=individual)

    assert latest_operation_findings_by_individual(program=program, individual_ids=[individual.pk]) == {}
    assert not qs_individuals_with_latest_operation_findings(program=program).exists()


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


def test_fail_rdp_operation_ignores_stale_attempt(
    running_biometric_operation: RdpOperation,
) -> None:
    assert (
        fail_rdp_operation(
            operation_id=running_biometric_operation.id,
            expected_attempt=running_biometric_operation.attempt + 1,
            error={"message": "failed"},
        )
        is False
    )


def test_finish_rdp_operation(
    running_biometric_operation: RdpOperation,
) -> None:
    from testutils.factories import BiometricRdpOperationFindingFactory, IndividualFactory

    old_finding = BiometricRdpOperationFindingFactory(operation=running_biometric_operation)
    individual = IndividualFactory(batch__program=running_biometric_operation.rdp.program, household=None)
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


def test_finish_rdp_operation_ignores_stale_attempt(
    running_biometric_operation: RdpOperation,
) -> None:
    assert (
        finish_rdp_operation(
            operation_id=running_biometric_operation.id,
            expected_attempt=running_biometric_operation.attempt + 1,
        )
        is False
    )


def test_finish_rdp_operation_preserves_findings_when_omitted(running_ocr_operation: RdpOperation) -> None:
    from testutils.factories import OcrRdpOperationFindingFactory

    finding = OcrRdpOperationFindingFactory(operation=running_ocr_operation)

    assert finish_rdp_operation(operation_id=running_ocr_operation.id)
    assert list(running_ocr_operation.findings.all()) == [finding]


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
    retry = OcrRdpOperationUnitFactory(
        operation=running_ocr_operation,
        status=RdpOperationUnit.Status.FAILURE,
        error={"message": "old"},
    )
    original_config = retry.config.copy()

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
    assert retry.error == ({} if expected else {"message": "old"})
    assert retry.config == original_config


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


def test_rdp_operation_unit_queries(running_ocr_operation: RdpOperation) -> None:
    from testutils.factories import OcrRdpOperationUnitFactory

    pending = OcrRdpOperationUnitFactory(operation=running_ocr_operation)
    OcrRdpOperationUnitFactory(operation=running_ocr_operation, status=RdpOperationUnit.Status.SUCCESS)

    assert list(pending_rdp_operation_units(operation_id=running_ocr_operation.id)) == [pending]
    assert has_rdp_operation_units(operation_id=running_ocr_operation.id) is True


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], None),
        ([RdpOperationUnit.Status.PENDING], None),
        ([RdpOperationUnit.Status.PENDING, RdpOperationUnit.Status.FAILURE], None),
        ([RdpOperationUnit.Status.SUCCESS], RdpOperation.Status.SUCCESS),
        ([RdpOperationUnit.Status.SUCCESS, RdpOperationUnit.Status.FAILURE], RdpOperation.Status.FAILURE),
    ],
    ids=["empty", "pending", "partly-failed", "success", "failure"],
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


@pytest.mark.parametrize(
    ("rdp_status", "attempt_offset"),
    [
        (Rdp.PushStatus.PENDING, 1),
        (Rdp.PushStatus.CANCELLED, 0),
    ],
    ids=["stale-attempt", "rdp-not-pending"],
)
def test_record_rdp_operation_error_ignores_inactive_operation(
    running_ocr_operation: RdpOperation,
    rdp_status: Rdp.PushStatus,
    attempt_offset: int,
) -> None:
    running_ocr_operation.rdp.status = rdp_status
    running_ocr_operation.rdp.save(update_fields=["status"])

    assert (
        record_rdp_operation_error(
            operation_id=running_ocr_operation.id,
            expected_attempt=running_ocr_operation.attempt + attempt_offset,
            error={"message": "failed"},
        )
        is False
    )

    running_ocr_operation.refresh_from_db()
    assert running_ocr_operation.status == RdpOperation.Status.RUNNING
