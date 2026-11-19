from collections.abc import Callable

from requests import Response, Session
from requests.exceptions import HTTPError, RequestException

from country_workspace.exceptions import RemoteError, RemoteUnavailableError


class BaseClient:
    session: Session

    def _err(
        self,
        operation: str,
        err: Exception,
        response: Response | None = None,
        *,
        error_cls: type[RemoteError] | type[RemoteUnavailableError] = RemoteError,
    ) -> RemoteError | RemoteUnavailableError:
        request = getattr(response, "request", None)
        target = f"{getattr(request, 'method', '')} {getattr(request, 'url', '')}".strip() or operation

        details = ""
        if response is not None:
            details = f". Status: {getattr(response, 'status_code', None)}. Response: {getattr(response, 'text', None)}"

        return error_cls(f"DedupEngine: {target} failed: {err}{details}")

    def _request[T](self, operation: str, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except HTTPError as exc:
            response = exc.response
            status_code = getattr(response, "status_code", None)
            error_cls = RemoteUnavailableError if isinstance(status_code, int) and status_code >= 500 else RemoteError
            raise self._err(operation, exc, response, error_cls=error_cls) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise self._err(operation, exc, getattr(exc, "response", None)) from exc
        except RequestException as exc:
            raise self._err(
                operation,
                exc,
                getattr(exc, "response", None),
                error_cls=RemoteUnavailableError,
            ) from exc
