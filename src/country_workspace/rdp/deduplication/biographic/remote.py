from collections.abc import Generator
from contextlib import contextmanager

from country_workspace.contrib.dedup_engine import (
    BiographicClient,
    DatasetState,
    make_biographic_client,
    parse_dataset_state,
)
from country_workspace.exceptions import RemoteError
from country_workspace.models import Program, RdpOperation


def program_route(program: Program) -> tuple[str, str]:
    """Return the business area slug and program code that address the program in DedupEngine."""
    business_area_slug = getattr(program.country_office, "slug", None)
    if not business_area_slug or not program.code:
        raise RemoteError("DedupEngine: program requires country_office.slug and code.")
    return business_area_slug, program.code


def dataset_id_of(operation: RdpOperation) -> int | None:
    """Return the DedupEngine dataset id of an operation, or None before its dataset was created."""
    return int(operation.external_id) if operation.external_id else None


@contextmanager
def make_operation_client(operation: RdpOperation) -> Generator[BiographicClient, None, None]:
    """Open a DedupEngine client bound to the dataset of an operation, when it already has one."""
    business_area_slug, program_code = program_route(operation.rdp.program)
    with make_biographic_client(
        business_area_slug=business_area_slug,
        program_code=program_code,
        dataset_id=dataset_id_of(operation),
    ) as client:
        yield client


def retrieve_operation_state(operation: RdpOperation) -> DatasetState | None:
    """Return the DedupEngine state of an operation dataset, or None when it does not exist."""
    if dataset_id_of(operation) is None:
        return None
    with make_operation_client(operation) as client:
        if (payload := client.retrieve_dataset_or_none()) is None:
            return None
    return parse_dataset_state(payload)
