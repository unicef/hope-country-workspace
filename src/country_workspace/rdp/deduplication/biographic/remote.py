from collections.abc import Generator
from contextlib import contextmanager

from country_workspace.contrib.dedup_engine import (
    BiographicClient,
    DatasetState,
    make_biographic_client,
    retrieve_dataset_state,
)
from country_workspace.exceptions import RemoteError
from country_workspace.models import Program, RdpOperation


def program_route(program: Program) -> tuple[str, str]:
    """Return the business area slug and program code that address the program in DedupEngine."""
    business_area_slug = getattr(program.country_office, "slug", None)
    if not business_area_slug or not program.code:
        raise RemoteError("DedupEngine: program requires country_office.slug and code.")
    return business_area_slug, program.code


@contextmanager
def make_operation_client(operation: RdpOperation) -> Generator[BiographicClient, None, None]:
    """Open a DedupEngine client bound to the dataset of an operation, which has the id of the operation."""
    business_area_slug, program_code = program_route(operation.rdp.program)
    with make_biographic_client(
        business_area_slug=business_area_slug,
        program_code=program_code,
        dataset_id=operation.id,
    ) as client:
        yield client


def retrieve_operation_state(operation: RdpOperation) -> DatasetState | None:
    """Return the DedupEngine state of the operation dataset, or None when it does not exist."""
    business_area_slug, program_code = program_route(operation.rdp.program)
    return retrieve_dataset_state(
        business_area_slug=business_area_slug,
        program_code=program_code,
        dataset_id=operation.id,
    )


def approve_operation_dataset(operation: RdpOperation) -> None:
    """Approve the DedupEngine dataset of an operation, which turns its people into the program population."""
    with make_operation_client(operation) as client:
        client.approve()


def reject_operation_dataset(operation: RdpOperation) -> None:
    """Reject the DedupEngine dataset of an operation. A rejected dataset is never matched against again."""
    with make_operation_client(operation) as client:
        client.reject()
