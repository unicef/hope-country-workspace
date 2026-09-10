from collections.abc import Callable
from dataclasses import dataclass

from country_workspace.exceptions import RemoteError, RemoteUnavailableError

from country_workspace.rdp.exceptions import RdpWorkflowError


@dataclass(slots=True, frozen=True)
class ActionCheck:
    allowed: bool
    reason: str | None = None

    def require(self) -> None:
        if not self.allowed:
            raise RdpWorkflowError({"errors": [self.reason or "Action is not allowed."]})


def require_policy_check(check: Callable[[], ActionCheck]) -> None:
    try:
        check().require()
    except (RemoteError, RemoteUnavailableError) as exc:
        raise RdpWorkflowError({"errors": [str(exc)]}) from exc
