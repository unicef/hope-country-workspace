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


@pytest.mark.parametrize(("external_id", "expected"), [("", None), ("42", 42)])
def test_dataset_id_of(biographic_operation: RdpOperation, external_id: str, expected: int | None) -> None:
    biographic_operation.external_id = external_id

    assert remote.dataset_id_of(biographic_operation) == expected


def test_make_operation_client(successful_biographic_operation: RdpOperation, mocker: MockerFixture) -> None:
    make_client = mocker.patch.object(remote, "make_biographic_client")
    program = successful_biographic_operation.rdp.program

    with remote.make_operation_client(successful_biographic_operation) as client:
        assert client is make_client.return_value.__enter__.return_value

    make_client.assert_called_once_with(
        business_area_slug=program.country_office.slug,
        program_code=program.code,
        dataset_id=42,
    )


def test_retrieve_operation_state_without_dataset(biographic_operation: RdpOperation, mocker: MockerFixture) -> None:
    make_client = mocker.patch.object(remote, "make_biographic_client")

    assert remote.retrieve_operation_state(biographic_operation) is None
    make_client.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [(None, None), ({"status": "deduplicated"}, DatasetState.DEDUPLICATED)],
)
def test_retrieve_operation_state(
    successful_biographic_operation: RdpOperation,
    mocker: MockerFixture,
    payload: dict | None,
    expected: DatasetState | None,
) -> None:
    make_client = mocker.patch.object(remote, "make_biographic_client")
    make_client.return_value.__enter__.return_value.retrieve_dataset_or_none.return_value = payload

    assert remote.retrieve_operation_state(successful_biographic_operation) == expected
