"""The shared lifecycle rules of DeduplicationBackend, exercised for every backend with its own remote states."""

from dataclasses import dataclass, replace

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DatasetState, DeduplicationSetState
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication.backend import DeduplicationBackend
from country_workspace.rdp.deduplication.biographic.backend import BIOGRAPHIC_BACKEND
from country_workspace.rdp.deduplication.biographic.forms import BiographicDeduplicationConfigForm
from country_workspace.rdp.deduplication.biometric.backend import BIOMETRIC_BACKEND
from country_workspace.rdp.deduplication.types import DeduplicationLogAction
from country_workspace.rdp.forms import ThresholdConfigForm

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Case:
    backend: DeduplicationBackend
    operation_fixture: str
    successful_operation_fixture: str
    # Remote states, by role.
    deduplicated: str
    running: str
    # Left behind without a rejection when the RDP is cancelled.
    non_blocking: tuple[str, ...]
    # Nothing to reject: the reject step is a no-op.
    nothing_to_reject: tuple[str, ...]
    # The remote set is in a state that cannot be rejected.
    cannot_reject: tuple[str, ...]
    # Not DEDUPLICATED: no clean replacement can be built.
    cannot_clean: tuple[str, ...]


CASES = {
    "biometric": Case(
        backend=BIOMETRIC_BACKEND,
        operation_fixture="biometric_operation",
        successful_operation_fixture="successful_biometric_operation",
        deduplicated=DeduplicationSetState.DEDUPLICATED,
        running=DeduplicationSetState.ENCODING_IN_PROGRESS,
        non_blocking=(
            DeduplicationSetState.APPROVED,
            DeduplicationSetState.REJECTED,
            DeduplicationSetState.ENCODING_FAILED,
        ),
        nothing_to_reject=(DeduplicationSetState.REJECTED,),
        cannot_reject=(DeduplicationSetState.APPROVED, DeduplicationSetState.ENCODING_IN_PROGRESS),
        cannot_clean=(DeduplicationSetState.APPROVED, DeduplicationSetState.READY),
    ),
    "biographic": Case(
        backend=BIOGRAPHIC_BACKEND,
        operation_fixture="biographic_operation",
        successful_operation_fixture="successful_biographic_operation",
        deduplicated=DatasetState.DEDUPLICATED,
        running=DatasetState.INDEXING,
        non_blocking=(
            DatasetState.PENDING,
            DatasetState.FAILED,
            DatasetState.APPROVED,
            DatasetState.REJECTED,
            DatasetState.CANCELED,
        ),
        nothing_to_reject=(
            DatasetState.PENDING,
            DatasetState.FAILED,
            DatasetState.APPROVED,
            DatasetState.REJECTED,
            DatasetState.CANCELED,
        ),
        cannot_reject=(DatasetState.INDEXING, DatasetState.DEDUPLICATING),
        cannot_clean=(DatasetState.APPROVED, DatasetState.PENDING, DatasetState.INDEXING),
    ),
}


@pytest.fixture(params=CASES)
def case(request: pytest.FixtureRequest) -> Case:
    return CASES[request.param]


@pytest.fixture
def operation(case: Case, request: pytest.FixtureRequest) -> RdpOperation:
    return request.getfixturevalue(case.operation_fixture)


@pytest.fixture
def successful_operation(case: Case, request: pytest.FixtureRequest) -> RdpOperation:
    return request.getfixturevalue(case.successful_operation_fixture)


@pytest.fixture
def backend(case: Case, mocker: MockerFixture) -> DeduplicationBackend:
    """The backend under test with its remote calls replaced by mocks."""
    return replace(
        case.backend,
        retrieve_state=mocker.Mock(return_value=None),
        approve_remote=mocker.Mock(),
        reject_remote=mocker.Mock(),
    )


def _last_log(operation: RdpOperation) -> dict:
    operation.refresh_from_db()
    return operation.log[-1]


def test_backends_declare_what_differs(case: Case) -> None:
    assert case.deduplicated in case.backend.rejectable_states
    assert case.backend.clean_state == case.deduplicated
    assert not case.backend.rejectable_states & case.backend.non_blocking_states


# --- cancellation ----------------------------------------------------------------------------------------


def test_cancellation_requires_rejection_of_a_scored_set(
    case: Case, backend: DeduplicationBackend, operation: RdpOperation
) -> None:
    backend.retrieve_state.return_value = case.deduplicated

    decision = backend.check_cancellation(operation)

    assert (decision.check.allowed, decision.required) == (True, True)
    backend.retrieve_state.assert_called_once_with(operation)


def test_cancellation_ignores_a_missing_set(backend: DeduplicationBackend, operation: RdpOperation) -> None:
    decision = backend.check_cancellation(operation)

    assert (decision.check.allowed, decision.required) == (True, False)


def test_cancellation_leaves_non_blocking_sets(
    case: Case, backend: DeduplicationBackend, operation: RdpOperation
) -> None:
    for state in case.non_blocking:
        backend.retrieve_state.return_value = state

        decision = backend.check_cancellation(operation)

        assert (decision.check.allowed, decision.required) == (True, False), state


def test_cancellation_is_denied_while_the_set_is_busy(
    case: Case, backend: DeduplicationBackend, operation: RdpOperation
) -> None:
    backend.retrieve_state.return_value = case.running

    decision = backend.check_cancellation(operation)

    assert not decision.check.allowed
    assert not decision.required
    assert f"can not cancel with {backend.remote_label} in state" in decision.check.reason


# --- clean RDP -------------------------------------------------------------------------------------------


def test_clean_requires_a_successful_operation(backend: DeduplicationBackend, operation: RdpOperation) -> None:
    check = backend.check_clean(operation)

    assert not check.allowed
    assert f"successful {backend.kind} deduplication is required" in check.reason
    backend.retrieve_state.assert_not_called()


def test_clean_accepts_a_scored_set(
    case: Case, backend: DeduplicationBackend, successful_operation: RdpOperation
) -> None:
    backend.retrieve_state.return_value = case.deduplicated

    assert backend.check_clean(successful_operation).allowed


def test_clean_denies_any_other_state(
    case: Case, backend: DeduplicationBackend, successful_operation: RdpOperation
) -> None:
    for state in (*case.cannot_clean, None):
        backend.retrieve_state.return_value = state

        check = backend.check_clean(successful_operation)

        assert not check.allowed, state
        assert f"can not create clean RDP with {backend.remote_label} in state" in check.reason


# --- rejection -------------------------------------------------------------------------------------------


def test_reject_rejects_a_scored_set_and_records_it(
    case: Case, backend: DeduplicationBackend, operation: RdpOperation
) -> None:
    backend.retrieve_state.return_value = case.deduplicated

    backend.reject(operation)

    backend.reject_remote.assert_called_once_with(operation)
    entry = _last_log(operation)
    assert entry["action"] == DeduplicationLogAction.REJECT_SET
    assert entry["result"] == {"success": True}


def test_reject_skips_a_missing_set(backend: DeduplicationBackend, operation: RdpOperation) -> None:
    backend.reject(operation)

    backend.reject_remote.assert_not_called()


def test_reject_skips_a_set_with_nothing_to_reject(
    case: Case, backend: DeduplicationBackend, operation: RdpOperation
) -> None:
    for state in case.nothing_to_reject:
        backend.retrieve_state.return_value = state

        backend.reject(operation)

    backend.reject_remote.assert_not_called()


def test_reject_refuses_a_set_that_cannot_be_rejected(
    case: Case, backend: DeduplicationBackend, operation: RdpOperation
) -> None:
    for state in case.cannot_reject:
        backend.retrieve_state.return_value = state

        with pytest.raises(RdpWorkflowError, match=f"can not reject {backend.remote_label}"):
            backend.reject(operation)

    backend.reject_remote.assert_not_called()


@pytest.mark.parametrize("error", [RemoteError("remote"), RemoteUnavailableError("down")])
def test_reject_wraps_a_failed_state_lookup(
    backend: DeduplicationBackend, operation: RdpOperation, error: Exception
) -> None:
    backend.retrieve_state.side_effect = error

    with pytest.raises(RdpWorkflowError, match=str(error)):
        backend.reject(operation)


@pytest.mark.parametrize("error", [RemoteError("remote"), RemoteUnavailableError("down")])
def test_reject_records_and_wraps_a_failed_rejection(
    case: Case, backend: DeduplicationBackend, operation: RdpOperation, error: Exception
) -> None:
    backend.retrieve_state.return_value = case.deduplicated
    backend.reject_remote.side_effect = error

    with pytest.raises(RdpWorkflowError, match=str(error)):
        backend.reject(operation)

    entry = _last_log(operation)
    assert entry["action"] == DeduplicationLogAction.REJECT_SET
    assert entry["result"] == {"success": False, "error": str(error)}


# --- approval --------------------------------------------------------------------------------------------


def test_approve_records_success(backend: DeduplicationBackend, successful_operation: RdpOperation) -> None:
    backend.approve(successful_operation)

    backend.approve_remote.assert_called_once_with(successful_operation)
    entry = _last_log(successful_operation)
    assert entry["action"] == DeduplicationLogAction.APPROVE_SET
    assert entry["result"] == {"success": True}


@pytest.mark.parametrize("error", [RemoteError("rejected"), RemoteUnavailableError("down")])
def test_approve_only_records_a_failure(
    backend: DeduplicationBackend, successful_operation: RdpOperation, error: Exception
) -> None:
    backend.approve_remote.side_effect = error

    backend.approve(successful_operation)

    assert _last_log(successful_operation)["result"] == {"success": False, "error": str(error)}


# --- backend declarations --------------------------------------------------------------------------------


def test_backends_match_their_operation_type(case: Case, operation: RdpOperation) -> None:
    assert case.backend.operation_type == operation.operation_type


def test_biographic_config_form_is_threshold_form() -> None:
    assert issubclass(BiographicDeduplicationConfigForm, ThresholdConfigForm)
    assert "duplicates" in BiographicDeduplicationConfigForm.rate_help_text
