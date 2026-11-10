import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DatasetState
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication.biographic import lifecycle

pytestmark = pytest.mark.django_db


@pytest.fixture
def state(mocker: MockerFixture):
    return mocker.patch.object(lifecycle, "retrieve_operation_state")


@pytest.mark.parametrize(
    ("dataset_state", "allowed", "required"),
    [
        (DatasetState.DEDUPLICATED, True, True),
        (None, True, False),
        (DatasetState.PENDING, True, False),
        (DatasetState.APPROVED, True, False),
        (DatasetState.REJECTED, True, False),
        (DatasetState.CANCELED, True, False),
        (DatasetState.INDEXING, False, False),
        (DatasetState.DEDUPLICATING, False, False),
    ],
)
def test_check_biographic_cancellation(
    biographic_operation: RdpOperation,
    state,
    dataset_state: DatasetState | None,
    allowed: bool,
    required: bool,
) -> None:
    state.return_value = dataset_state

    decision = lifecycle.check_biographic_cancellation(biographic_operation)

    assert (decision.check.allowed, decision.required) == (allowed, required)
    assert allowed or "can not cancel" in decision.check.reason


def test_check_biographic_clean_requires_successful_operation(biographic_operation: RdpOperation, state) -> None:
    check = lifecycle.check_biographic_clean(biographic_operation)

    assert not check.allowed
    assert "successful biographic deduplication" in check.reason
    state.assert_not_called()


@pytest.mark.parametrize(
    ("dataset_state", "allowed"),
    [(DatasetState.DEDUPLICATED, True), (DatasetState.APPROVED, False), (None, False)],
)
def test_check_biographic_clean_checks_remote_state(
    successful_biographic_operation: RdpOperation,
    state,
    dataset_state: DatasetState | None,
    allowed: bool,
) -> None:
    state.return_value = dataset_state

    check = lifecycle.check_biographic_clean(successful_biographic_operation)

    assert check.allowed is allowed
    assert allowed or "can not create clean RDP" in check.reason


def test_reject_cancelled_dataset(biographic_operation: RdpOperation, state, mocker: MockerFixture) -> None:
    state.return_value = DatasetState.DEDUPLICATED
    reject = mocker.patch.object(lifecycle, "reject_biographic_dataset")

    lifecycle.reject_cancelled_biographic_dataset(biographic_operation)

    reject.assert_called_once_with(biographic_operation)


@pytest.mark.parametrize("dataset_state", [None, DatasetState.REJECTED, DatasetState.CANCELED])
def test_reject_cancelled_dataset_skips_finished_dataset(
    biographic_operation: RdpOperation,
    state,
    mocker: MockerFixture,
    dataset_state: DatasetState | None,
) -> None:
    state.return_value = dataset_state
    reject = mocker.patch.object(lifecycle, "reject_biographic_dataset")

    lifecycle.reject_cancelled_biographic_dataset(biographic_operation)

    reject.assert_not_called()


def test_reject_cancelled_dataset_rejects_running_dataset(biographic_operation: RdpOperation, state) -> None:
    state.return_value = DatasetState.INDEXING

    with pytest.raises(RdpWorkflowError, match="can not reject"):
        lifecycle.reject_cancelled_biographic_dataset(biographic_operation)


@pytest.mark.parametrize("error", [RemoteError("remote"), RemoteUnavailableError("down")])
def test_reject_cancelled_dataset_wraps_remote_error(
    biographic_operation: RdpOperation,
    state,
    error: Exception,
) -> None:
    state.side_effect = error

    with pytest.raises(RdpWorkflowError, match=str(error)):
        lifecycle.reject_cancelled_biographic_dataset(biographic_operation)
