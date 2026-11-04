from uuid import UUID

import pytest
from django.db import IntegrityError
from django.utils import timezone
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.models import Individual, Program, Rdp, RdpOperation, RdpOperationUnit
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.lifecycle import clean
from country_workspace.rdp.policy import ActionCheck
from country_workspace.rdp.types import ThresholdType


pytestmark = pytest.mark.django_db


@pytest.fixture
def reviewed_rdp(people_rdp: tuple[Rdp, list[Individual]], mocker: MockerFixture) -> Rdp:
    from testutils.factories import (
        BiometricRdpOperationFactory,
        BiometricRdpOperationFindingFactory,
        OcrRdpOperationFactory,
        OcrRdpOperationFindingFactory,
        OcrRdpOperationUnitFactory,
    )

    rdp, individuals = people_rdp
    rdp.status = Rdp.PushStatus.REVIEW_PENDING
    rdp.save(update_fields=["status"])
    rdp.individuals.update(last_checked=timezone.now(), errors={})
    biometric = BiometricRdpOperationFactory(
        rdp=rdp,
        status=RdpOperation.Status.SUCCESS,
        config={"threshold_type": ThresholdType.RATE, "threshold_value": "0", "other": "kept"},
    )
    BiometricRdpOperationFindingFactory(operation=biometric, individual=individuals[1])
    ocr = OcrRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.SUCCESS)
    OcrRdpOperationUnitFactory(operation=ocr, individual=individuals[0], status=RdpOperationUnit.Status.SUCCESS)
    OcrRdpOperationFindingFactory(operation=ocr, individual=individuals[0])
    mocker.patch.object(clean, "retrieve_deduplication_set_state", return_value=DeduplicationSetState.DEDUPLICATED)
    return rdp


@pytest.mark.parametrize(
    ("status", "operation_status", "state", "allowed"),
    [
        (Rdp.PushStatus.PENDING, RdpOperation.Status.SUCCESS, DeduplicationSetState.DEDUPLICATED, False),
        (Rdp.PushStatus.REVIEW_PENDING, None, None, True),
        (Rdp.PushStatus.REVIEW_PENDING, RdpOperation.Status.FAILURE, DeduplicationSetState.DEDUPLICATED, False),
        (Rdp.PushStatus.REVIEW_PENDING, RdpOperation.Status.SUCCESS, DeduplicationSetState.READY, False),
        (Rdp.PushStatus.REVIEW_PENDING, RdpOperation.Status.SUCCESS, DeduplicationSetState.DEDUPLICATED, True),
    ],
)
def test_clean_rdp_check(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    status: Rdp.PushStatus,
    operation_status: RdpOperation.Status | None,
    state: DeduplicationSetState | None,
    allowed: bool,
) -> None:
    rdp.status = status
    operation = biometric_operation if operation_status is not None else None
    if operation_status is not None:
        biometric_operation.status = operation_status
    mocker.patch.object(clean, "biometric_operation_for_rdp", return_value=operation)
    retrieve = mocker.patch.object(clean, "retrieve_deduplication_set_state", return_value=state)

    check, result = clean._clean_rdp_check(rdp)

    assert check.allowed is allowed
    assert result is (operation if allowed else None)
    if status != Rdp.PushStatus.REVIEW_PENDING or operation_status != RdpOperation.Status.SUCCESS:
        retrieve.assert_not_called()


def test_clean_rdp_check_during_program_cleanup(review_pending_rdp: Rdp, mocker: MockerFixture) -> None:
    review_pending_rdp.program.cleanup_in_progress = True
    operation = mocker.patch.object(clean, "biometric_operation_for_rdp")
    retrieve = mocker.patch.object(clean, "retrieve_deduplication_set_state")

    check, result = clean._clean_rdp_check(review_pending_rdp)

    assert check.allowed is False
    assert "cleanup" in (check.reason or "")
    assert result is None
    operation.assert_not_called()
    retrieve.assert_not_called()


def test_create_clean_rdp_rejects_failed_check(review_pending_rdp: Rdp, mocker: MockerFixture) -> None:
    check = ActionCheck(False, "blocked")
    mocker.patch.object(clean, "_clean_rdp_check", return_value=(check, None))

    assert clean.create_clean_rdp(review_pending_rdp.pk, user_id=1, clean_operation_ids=set()) == (check, None)


@pytest.mark.parametrize("invalid", ["empty", "unknown", "no_beneficiaries"])
def test_create_clean_rdp_rejects_invalid_selection(reviewed_rdp: Rdp, mocker: MockerFixture, invalid: str) -> None:
    ocr = reviewed_rdp.operations.get(operation_type=RdpOperation.Type.OCR)
    operation_ids = {ocr.pk}
    if invalid == "empty":
        operation_ids = set()
    elif invalid == "unknown":
        operation_ids = {UUID(int=0)}
    else:
        mocker.patch.object(clean, "clean_rdp_selection", return_value=(False, []))
    create = mocker.patch.object(clean, "create_rdp")

    check, result = clean.create_clean_rdp(reviewed_rdp.pk, user_id=1, clean_operation_ids=operation_ids)

    assert check.allowed is False
    assert result is None
    create.assert_not_called()
    reviewed_rdp.refresh_from_db()
    assert reviewed_rdp.status == Rdp.PushStatus.REVIEW_PENDING


@pytest.mark.parametrize("changed", ["status", "selection", "cleanup", "biometric_status", "thresholds"])
def test_create_clean_rdp_rechecks_state_after_lock(reviewed_rdp: Rdp, mocker: MockerFixture, changed: str) -> None:
    from testutils.factories import BiometricRdpOperationFindingFactory

    prepare = clean._prepare_clean_rdp_plan

    def change_after_plan(
        *, rdp: Rdp, clean_operation_ids: set[UUID]
    ) -> tuple[ActionCheck, clean._CleanRdpPlan | None]:
        result = prepare(rdp=rdp, clean_operation_ids=clean_operation_ids)
        if changed == "status":
            Rdp.objects.filter(pk=rdp.pk).update(status=Rdp.PushStatus.PENDING)
        elif changed == "selection":
            mocker.patch.object(clean, "clean_rdp_selection", return_value=(False, []))
        elif changed == "cleanup":
            Program.objects.filter(pk=rdp.program_id).update(cleanup_in_progress=True)
        elif changed == "biometric_status":
            rdp.operations.filter(operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION).update(
                status=RdpOperation.Status.FAILURE
            )
        else:
            BiometricRdpOperationFindingFactory(
                operation=rdp.operations.get(operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION),
                individual=rdp.individuals.order_by("pk").last(),
            )
        return result

    mocker.patch.object(clean, "_prepare_clean_rdp_plan", side_effect=change_after_plan)
    create = mocker.patch.object(clean, "create_rdp")
    operation_id = reviewed_rdp.operations.get(operation_type=RdpOperation.Type.OCR).pk

    check, result = clean.create_clean_rdp(reviewed_rdp.pk, user_id=1, clean_operation_ids={operation_id})

    assert check.allowed is False
    assert result is None
    create.assert_not_called()


@pytest.mark.parametrize(
    ("with_biometric", "clean_all"), [(False, False), (True, False), (True, True)], ids=["ocr", "mixed", "all"]
)
def test_create_clean_rdp(reviewed_rdp: Rdp, mocker: MockerFixture, with_biometric: bool, clean_all: bool) -> None:
    if not with_biometric:
        reviewed_rdp.operations.filter(operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION).delete()
    operations = list(reviewed_rdp.operations.order_by("operation_type"))
    clean_ids = {
        operation.pk for operation in operations if clean_all or operation.operation_type == RdpOperation.Type.OCR
    }
    members = list(reviewed_rdp.individuals.order_by("pk"))
    expected_members = members[2:] if clean_all else members[1:]
    schedule = mocker.patch.object(clean, "schedule_rdp_processing")
    reject = mocker.patch.object(clean, "schedule_cancelled_rdp_set_rejection", return_value=mocker.Mock(pk=456))

    check, result = clean.create_clean_rdp(
        reviewed_rdp.pk, user_id=reviewed_rdp.pushed_by_id, clean_operation_ids=clean_ids
    )

    assert check.allowed is True
    assert result is not None
    assert result.program_id == reviewed_rdp.program_id
    assert result.pushed_by_id == reviewed_rdp.pushed_by_id
    assert list(result.individuals.order_by("pk")) == expected_members
    assert set(result.operations.values_list("status", flat=True)) == {RdpOperation.Status.PENDING}
    configs = {operation.operation_type: operation.config for operation in result.operations.all()}
    assert configs[RdpOperation.Type.OCR] == {"threshold_type": "count", "threshold_value": "0"}
    reviewed_rdp.refresh_from_db()
    assert reviewed_rdp.status == Rdp.PushStatus.CANCELLED
    entry = reviewed_rdp.operation_log[-1]
    assert entry["action"] == RdpLogEntryType.REVIEW_DECISION
    assert entry["result"]["new_rdp_id"] == result.pk
    assert entry["result"]["clean_operation_ids"] == sorted(map(str, clean_ids))
    assert entry["result"]["approved_operation_ids"] == sorted(
        str(operation.pk) for operation in operations if operation.pk not in clean_ids
    )
    if with_biometric:
        biometric = reviewed_rdp.operations.get(operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION)
        assert configs[biometric.operation_type] == {
            "threshold_type": "count",
            "threshold_value": "0" if clean_all else "1",
            "other": "kept",
        }
        assert biometric.config["threshold_type"] == ThresholdType.RATE
        reject.assert_called_once_with(
            rdp=reviewed_rdp,
            user_id=reviewed_rdp.pushed_by_id,
            deduplication_set_id=str(biometric.pk),
            clean_rdp_id=result.pk,
        )
        schedule.assert_not_called()
    else:
        schedule.assert_called_once_with(rdp=result)
        reject.assert_not_called()


def test_clean_rdp_operation_configs_preserves_unexceeded_config(reviewed_rdp: Rdp) -> None:
    biometric = reviewed_rdp.operations.get(operation_type=RdpOperation.Type.BIOMETRIC_DEDUPLICATION)
    biometric.config["threshold_value"] = "100"
    biometric.save(update_fields=["config"])
    operation_ids = {reviewed_rdp.operations.get(operation_type=RdpOperation.Type.OCR).pk}
    __, plan = clean._prepare_clean_rdp_plan(rdp=reviewed_rdp, clean_operation_ids=operation_ids)
    assert plan is not None

    configs = clean._clean_rdp_operation_configs(rdp=reviewed_rdp, clean_operation_ids=operation_ids, plan=plan)

    assert next(config["config"] for config in configs if config["operation_type"] == biometric.operation_type) == (
        biometric.config
    )


def test_create_clean_rdp_converts_integrity_error(reviewed_rdp: Rdp, mocker: MockerFixture) -> None:
    mocker.patch.object(clean, "create_rdp", side_effect=IntegrityError("uniq_non_terminal_rdp_per_program"))
    operation_id = reviewed_rdp.operations.get(operation_type=RdpOperation.Type.OCR).pk

    with pytest.raises(RdpWorkflowError, match="unfinished"):
        clean.create_clean_rdp(reviewed_rdp.pk, user_id=reviewed_rdp.pushed_by_id, clean_operation_ids={operation_id})

    reviewed_rdp.refresh_from_db()
    assert reviewed_rdp.status == Rdp.PushStatus.REVIEW_PENDING
