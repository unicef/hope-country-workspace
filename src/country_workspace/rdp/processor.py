from collections.abc import Callable, Sequence
from typing import Any, Final, NamedTuple

from country_workspace.exceptions import RemoteError, RemoteUnavailableError


class ErrorConfig(NamedTuple):
    MAX_ERRORS: int = 300
    MAX_ERROR_LEN: int = 2000
    MAX_IDS_HINT: int = 5
    MARKER: str = "… further errors truncated …"


ERROR_CONFIG: Final[ErrorConfig] = ErrorConfig()


class ProcessorBase:
    """Shared processor primitives."""

    PREFIX: str = "Processor"

    def __init__(self) -> None:
        self.total: dict[str, Any] = {"errors": []}

    @property
    def has_errors(self) -> bool:
        """Return True when at least one error was collected."""
        return bool(self.total.get("errors"))

    @staticmethod
    def _ids_hint(ids: Sequence[int]) -> str:
        """Return a short ids hint suitable for logs."""
        limit = ERROR_CONFIG.MAX_IDS_HINT
        if not ids:
            return "[]"
        if len(ids) <= limit:
            return str(ids)
        head = ", ".join(map(str, ids[:limit]))
        return f"[{head}, …]"

    def _err(self, msg: str) -> None:
        """Append an error into total['errors']; truncate long text; cap the list with a marker."""
        errors: list[str] = self.total["errors"]
        if errors and errors[-1] == ERROR_CONFIG.MARKER:
            return
        if len(errors) >= ERROR_CONFIG.MAX_ERRORS - 1:
            errors.append(ERROR_CONFIG.MARKER)
            return
        if len(msg) > ERROR_CONFIG.MAX_ERROR_LEN:
            msg = f"{msg[: ERROR_CONFIG.MAX_ERROR_LEN - 1]}…"
        errors.append(msg)

    def _fmt_fail(
        self,
        subject: str,
        msg: str,
        *,
        ids: Sequence[int] | None = None,
        response: object | None = None,
    ) -> str:
        ids_part = f" ids={self._ids_hint(ids)}" if ids is not None else ""
        line = f"{self.PREFIX}: {subject}: {msg}{ids_part}"
        return f"{line}. Response: {response}" if response is not None else line

    def fail(
        self,
        subject: str,
        msg: str,
        *,
        ids: Sequence[int] | None = None,
        response: object | None = None,
    ) -> None:
        self._err(self._fmt_fail(subject, msg, ids=ids, response=response))

    def try_remote(
        self,
        subject: str,
        fn: Callable[[], Any],
        *,
        ids: Sequence[int] | None = None,
    ) -> Any | None:
        try:
            return fn()
        except (RemoteError, RemoteUnavailableError) as e:
            self.fail(subject, f"request failed. {e}", ids=ids)
            return None

    def run_remote(
        self,
        subject: str,
        fn: Callable[[], object],
        *,
        ids: Sequence[int] | None = None,
    ) -> bool:
        try:
            fn()
        except (RemoteError, RemoteUnavailableError) as e:
            self.fail(subject, f"request failed. {e}", ids=ids)
            return False
        return True
