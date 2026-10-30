from typing import TYPE_CHECKING

from country_workspace.exceptions import RemoteError

from .factory import make_client
from .schemas import BiographicSet, BiographicSetState

if TYPE_CHECKING:
    from country_workspace.models import Program


def parse_set_state(payload: BiographicSet) -> BiographicSetState:
    """Return the validated state of a biographic set response."""
    try:
        return BiographicSetState(payload["status"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RemoteError(f"Biographic DedupEngine: malformed set response: {payload!r}") from exc


def retrieve_biographic_set_state(program: "Program", dataset_id: int | str) -> BiographicSetState | None:
    """Return the current state of a biographic set, or None if DedupEngine does not know it."""
    with make_client(program, dataset_id=dataset_id) as client:
        if (payload := client.retrieve_dataset_or_none()) is None:
            return None
    return parse_set_state(payload)
