import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState
from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.biometric import remote

pytestmark = pytest.mark.django_db


def test_make_operation_client_uses_the_operation_id_as_set_id(
    biometric_operation: RdpOperation, mocker: MockerFixture
) -> None:
    make_client = mocker.patch.object(remote, "make_biometric_client")

    with remote.make_operation_client(biometric_operation) as client:
        assert client is make_client.return_value.__enter__.return_value

    make_client.assert_called_once_with(
        biometric_operation.rdp.program.unicef_id,
        deduplication_set_id=str(biometric_operation.id),
    )


@pytest.mark.parametrize("state", [None, DeduplicationSetState.DEDUPLICATED])
def test_retrieve_operation_state(
    biometric_operation: RdpOperation, mocker: MockerFixture, state: DeduplicationSetState | None
) -> None:
    retrieve = mocker.patch.object(remote, "retrieve_deduplication_set_state", return_value=state)

    assert remote.retrieve_operation_state(biometric_operation) == state
    retrieve.assert_called_once_with(
        group_reference_id=biometric_operation.rdp.program.unicef_id,
        deduplication_set_id=str(biometric_operation.id),
    )


@pytest.mark.parametrize("method", ["approve", "reject"])
def test_approve_and_reject_operation_set(
    biometric_operation: RdpOperation, mocker: MockerFixture, method: str
) -> None:
    client = mocker.patch.object(remote, "make_biometric_client").return_value.__enter__.return_value

    getattr(remote, f"{method}_operation_set")(biometric_operation)

    getattr(client, method).assert_called_once_with()
