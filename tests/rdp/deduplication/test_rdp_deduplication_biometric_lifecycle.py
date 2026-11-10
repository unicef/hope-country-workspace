import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication.biometric import lifecycle

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("state", "allowed", "required"),
    [
        (DeduplicationSetState.DEDUPLICATED, True, True),
        (None, True, False),
        (DeduplicationSetState.APPROVED, True, False),
        (DeduplicationSetState.REJECTED, True, False),
        (DeduplicationSetState.ENCODING_IN_PROGRESS, False, False),
    ],
)
def test_check_biometric_cancellation(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    state: DeduplicationSetState | None,
    allowed: bool,
    required: bool,
) -> None:
    retrieve = mocker.patch.object(lifecycle, "retrieve_deduplication_set_state", return_value=state)

    decision = lifecycle.check_biometric_cancellation(biometric_operation)

    assert (decision.check.allowed, decision.required) == (allowed, required)
    assert allowed or "can not cancel" in decision.check.reason
    retrieve.assert_called_once_with(
        group_reference_id=biometric_operation.rdp.program.unicef_id,
        deduplication_set_id=str(biometric_operation.id),
    )


def test_check_biometric_clean_requires_successful_operation(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    retrieve = mocker.patch.object(lifecycle, "retrieve_deduplication_set_state")

    check = lifecycle.check_biometric_clean(biometric_operation)

    assert not check.allowed
    assert "successful biometric deduplication" in check.reason
    retrieve.assert_not_called()


@pytest.mark.parametrize(
    ("state", "allowed"),
    [
        (DeduplicationSetState.DEDUPLICATED, True),
        (DeduplicationSetState.APPROVED, False),
        (None, False),
    ],
)
def test_check_biometric_clean_checks_remote_state(
    successful_biometric_operation: RdpOperation,
    mocker: MockerFixture,
    state: DeduplicationSetState | None,
    allowed: bool,
) -> None:
    mocker.patch.object(lifecycle, "retrieve_deduplication_set_state", return_value=state)

    check = lifecycle.check_biometric_clean(successful_biometric_operation)

    assert check.allowed is allowed
    assert allowed or "can not create clean RDP" in check.reason


def test_reject_biometric_set_rejects_rejectable_set(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(lifecycle, "retrieve_deduplication_set_state", return_value=DeduplicationSetState.DEDUPLICATED)
    reject = mocker.patch.object(lifecycle, "reject_deduplication_set")

    lifecycle.reject_biometric_set(biometric_operation)

    reject.assert_called_once_with(
        operation_id=biometric_operation.id,
        group_reference_id=biometric_operation.rdp.program.unicef_id,
    )


@pytest.mark.parametrize("state", [None, DeduplicationSetState.REJECTED], ids=["missing", "already_rejected"])
def test_reject_biometric_set_skips_completed_cleanup(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    state: DeduplicationSetState | None,
) -> None:
    mocker.patch.object(lifecycle, "retrieve_deduplication_set_state", return_value=state)
    reject = mocker.patch.object(lifecycle, "reject_deduplication_set")

    lifecycle.reject_biometric_set(biometric_operation)

    reject.assert_not_called()


def test_reject_biometric_set_rejects_non_rejectable_state(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(
        lifecycle,
        "retrieve_deduplication_set_state",
        return_value=DeduplicationSetState.ENCODING_IN_PROGRESS,
    )

    with pytest.raises(RdpWorkflowError, match="can not reject"):
        lifecycle.reject_biometric_set(biometric_operation)


@pytest.mark.parametrize(
    "error",
    [RemoteError("remote"), RemoteUnavailableError("unavailable")],
    ids=["remote_error", "unavailable"],
)
def test_reject_biometric_set_wraps_remote_error(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    error: Exception,
) -> None:
    mocker.patch.object(lifecycle, "retrieve_deduplication_set_state", side_effect=error)

    with pytest.raises(RdpWorkflowError, match=str(error)):
        lifecycle.reject_biometric_set(biometric_operation)


def test_approve_biometric_set(biometric_operation: RdpOperation, mocker: MockerFixture) -> None:
    approve = mocker.patch.object(lifecycle, "approve_deduplication_set_after_successful_push")

    lifecycle.approve_biometric_set(biometric_operation)

    approve.assert_called_once_with(
        operation_id=biometric_operation.id,
        group_reference_id=biometric_operation.rdp.program.unicef_id,
    )
