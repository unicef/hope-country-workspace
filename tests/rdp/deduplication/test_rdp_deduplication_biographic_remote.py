import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DatasetState
from country_workspace.exceptions import RemoteError
from country_workspace.models import RdpOperation
from country_workspace.rdp.deduplication.biographic import remote

pytestmark = pytest.mark.django_db


def test_program_route(biographic_operation: RdpOperation) -> None:
    program = biographic_operation.rdp.program

    assert remote.program_route(program) == (program.country_office.slug, program.code)


@pytest.mark.parametrize("missing", ["code", "slug"])
def test_program_route_requires_slug_and_code(biographic_operation: RdpOperation, missing: str) -> None:
    program = biographic_operation.rdp.program
    if missing == "code":
        program.code = ""
    else:
        program.country_office.slug = ""

    with pytest.raises(RemoteError, match=r"country_office\.slug and code"):
        remote.program_route(program)


def test_make_operation_client_uses_the_operation_id_as_dataset_id(
    biographic_operation: RdpOperation, mocker: MockerFixture
) -> None:
    make_client = mocker.patch.object(remote, "make_biographic_client")
    program = biographic_operation.rdp.program

    with remote.make_operation_client(biographic_operation) as client:
        assert client is make_client.return_value.__enter__.return_value

    make_client.assert_called_once_with(
        business_area_slug=program.country_office.slug,
        program_code=program.code,
        dataset_id=biographic_operation.id,
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [(None, None), (DatasetState.DEDUPLICATED, DatasetState.DEDUPLICATED)],
)
def test_retrieve_operation_state(
    biographic_operation: RdpOperation,
    mocker: MockerFixture,
    state: DatasetState | None,
    expected: DatasetState | None,
) -> None:
    retrieve = mocker.patch.object(remote, "retrieve_dataset_state", return_value=state)
    program = biographic_operation.rdp.program

    assert remote.retrieve_operation_state(biographic_operation) == expected
    retrieve.assert_called_once_with(
        business_area_slug=program.country_office.slug,
        program_code=program.code,
        dataset_id=biographic_operation.id,
    )


@pytest.mark.parametrize("method", ["approve", "reject"])
def test_approve_and_reject_operation_dataset(
    biographic_operation: RdpOperation, mocker: MockerFixture, method: str
) -> None:
    client = mocker.patch.object(remote, "make_biographic_client").return_value.__enter__.return_value

    getattr(remote, f"{method}_operation_dataset")(biographic_operation)

    getattr(client, method).assert_called_once_with()
