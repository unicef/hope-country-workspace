import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.biographic import actions
from country_workspace.rdp.deduplication.types import DeduplicationLogAction

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(mocker: MockerFixture) -> object:
    context = mocker.patch.object(actions, "make_operation_client")
    return context.return_value.__enter__.return_value


def _log(operation: RdpOperation) -> dict:
    operation.refresh_from_db()
    return operation.log[-1]


def test_approve_without_dataset_is_noop(biographic_operation: RdpOperation, client: object) -> None:
    actions.approve_biographic_dataset_after_successful_push(biographic_operation)

    client.approve.assert_not_called()
    biographic_operation.refresh_from_db()
    assert not biographic_operation.log


def test_approve(successful_biographic_operation: RdpOperation, client: object) -> None:
    actions.approve_biographic_dataset_after_successful_push(successful_biographic_operation)

    client.approve.assert_called_once_with()
    entry = _log(successful_biographic_operation)
    assert entry["action"] == DeduplicationLogAction.APPROVE_SET
    assert entry["result"] == {"success": True}


@pytest.mark.parametrize("error", [RemoteError("rejected"), RemoteUnavailableError("down")])
def test_approve_records_remote_failure(
    successful_biographic_operation: RdpOperation,
    client: object,
    error: Exception,
) -> None:
    client.approve.side_effect = error

    actions.approve_biographic_dataset_after_successful_push(successful_biographic_operation)

    entry = _log(successful_biographic_operation)
    assert entry["result"] == {"success": False, "error": str(error)}


def test_reject(successful_biographic_operation: RdpOperation, client: object) -> None:
    actions.reject_biographic_dataset(successful_biographic_operation)

    client.reject.assert_called_once_with()
    entry = _log(successful_biographic_operation)
    assert entry["action"] == DeduplicationLogAction.REJECT_SET
    assert entry["result"] == {"success": True}


@pytest.mark.parametrize("error", [RemoteError("rejected"), RemoteUnavailableError("down")])
def test_reject_records_and_raises_remote_failure(
    successful_biographic_operation: RdpOperation,
    client: object,
    error: Exception,
) -> None:
    client.reject.side_effect = error

    with pytest.raises(type(error)):
        actions.reject_biographic_dataset(successful_biographic_operation)

    entry = _log(successful_biographic_operation)
    assert entry["result"] == {"success": False, "error": str(error)}
