from collections.abc import Collection

from country_workspace.exceptions import RemoteError
from country_workspace.models import RdpOperation
from country_workspace.rdp.repository import qs_individuals_by_pks, qs_individuals_for_rdp


def rdp_individual_pks(operation: RdpOperation) -> set[int]:
    """Return the ids of the individuals currently in the RDP of an operation."""
    return set(qs_individuals_for_rdp(rdp=operation.rdp).values_list("pk", flat=True))


def parse_individual_id(reference_pk: object, label: str) -> int:
    """Return the Individual id referenced by a DedupEngine finding."""
    if not isinstance(reference_pk, str):
        raise RemoteError(f"DedupEngine: invalid {label}={reference_pk!r}")
    try:
        return int(reference_pk)
    except ValueError as exc:
        raise RemoteError(f"DedupEngine: invalid Individual {label}={reference_pk!r}") from exc


def require_rdp_individual(individual_id: int, rdp_pks: Collection[int]) -> int:
    """Return the Individual id of a finding, which must belong to the RDP."""
    if individual_id not in rdp_pks:
        raise RemoteError(f"DedupEngine: Individual id={individual_id} is not part of the current RDP.")
    return individual_id


def local_individual_pks(operation: RdpOperation, pks: Collection[int]) -> set[int]:
    """Return which of the given ids are Individuals of the operation program.

    A finding can point at a person this workspace does not hold, for example one deleted by Clean Program.
    Such a match keeps its details but has no `related_individual`.
    """
    return set(
        qs_individuals_by_pks(pks).filter(batch__program_id=operation.rdp.program_id).values_list("pk", flat=True)
    )
