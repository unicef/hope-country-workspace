from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final, cast

from requests import Response, Session
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    RequestException,
    Timeout as RequestsTimeout,
)

from country_workspace.contrib.dedup_engine.endpoint import ensure_trailing_slash, url_join
from country_workspace.exceptions import RemoteError, RemoteUnavailableError

from .schemas import (
    BiographicFinding,
    BiographicRecord,
    BiographicSet,
    CreateBiographicSet,
    PaginatedBiographicFindings,
    RecordsBatchResult,
)

TIMEOUT: Final[tuple[int, int]] = (10, 20)
UPLOAD_TIMEOUT: Final[tuple[int, int]] = (10, 120)
FINDINGS_PAGE_SIZE: Final[int] = 10_000


@dataclass(slots=True)
class BiographicClient:
    """Client of the DedupEngine biographic API for one program.

    Every route lives under `{base_url}/{business_area}/{program_code}/datasets/`;
    DedupEngine lowercases both, so the program is identified by them alone.
    """

    session: Session
    base_url: str
    business_area: str
    program_code: str
    dataset_id: int | None = None

    @property
    def datasets_url(self) -> str:
        return ensure_trailing_slash(url_join(self.base_url, self.business_area, self.program_code, "datasets"))

    def _dataset_url(self, *paths: str) -> str:
        if self.dataset_id is None:
            raise RemoteError("Biographic DedupEngine: dataset_id is not set")
        return ensure_trailing_slash(url_join(self.datasets_url, str(self.dataset_id), *paths))

    def _err(
        self,
        operation: str,
        err: Exception,
        response_obj: Response | None = None,
        *,
        error_cls: type[RemoteError] | type[RemoteUnavailableError] = RemoteError,
    ) -> RemoteError | RemoteUnavailableError:
        req = getattr(response_obj, "request", None) if response_obj is not None else None
        target = f"{getattr(req, 'method', '')} {getattr(req, 'url', '')}".strip() or operation

        details = ""
        if response_obj is not None:
            details = f". Status: {response_obj.status_code}. Response: {response_obj.text}"

        return error_cls(f"Biographic DedupEngine: {target} failed: {err}{details}")

    def _request[T](self, operation: str, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except (RequestsConnectionError, RequestsTimeout) as exc:
            raise self._err(operation, exc, getattr(exc, "response", None), error_cls=RemoteUnavailableError) from exc
        except HTTPError as exc:
            status_code = getattr(exc.response, "status_code", None)
            error_cls = RemoteUnavailableError if isinstance(status_code, int) and status_code >= 500 else RemoteError
            raise self._err(operation, exc, exc.response, error_cls=error_cls) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise self._err(operation, exc, getattr(exc, "response", None)) from exc
        except RequestException as exc:
            raise self._err(operation, exc, getattr(exc, "response", None), error_cls=RemoteUnavailableError) from exc

    def _get(self, url: str, *, params: Mapping[str, str] | None = None) -> Any:
        result = self.session.get(url, params=params, timeout=TIMEOUT)
        result.raise_for_status()
        return result.json()

    def _post(
        self,
        url: str,
        body: Mapping[str, Any] | None = None,
        *,
        timeout: tuple[int, int] = TIMEOUT,
    ) -> Any:
        kwargs: dict[str, Any] = {"json": body} if body is not None else {}
        result = self.session.post(url, timeout=timeout, **kwargs)
        result.raise_for_status()
        return result.json() if result.content else None

    def create_dataset(self, notification_url: str | None = None) -> BiographicSet:
        """Create an empty set and remember its id."""
        payload: CreateBiographicSet = {}
        if notification_url:
            payload["notification_url"] = notification_url
            payload["notify"] = True

        created = cast(
            "BiographicSet",
            self._request("create_dataset", lambda: self._post(self.datasets_url, cast("Mapping", payload))),
        )
        self.dataset_id = created["dataset_id"]
        return created

    def retrieve_dataset(self) -> BiographicSet:
        return cast("BiographicSet", self._request("retrieve_dataset", lambda: self._get(self._dataset_url())))

    def retrieve_dataset_or_none(self) -> BiographicSet | None:
        """Retrieve the set, or None when DedupEngine does not know it."""

        def retrieve() -> BiographicSet | None:
            try:
                return cast("BiographicSet", self._get(self._dataset_url()))
            except HTTPError as exc:
                if getattr(exc.response, "status_code", None) == HTTPStatus.NOT_FOUND:
                    return None
                raise

        return self._request("retrieve_dataset", retrieve)

    def upload_records(self, records: list[BiographicRecord]) -> RecordsBatchResult:
        """Add a batch of people to a pending set. Re-sending a `reference_pk` replaces it."""
        return cast(
            "RecordsBatchResult",
            self._request(
                "upload_records",
                lambda: self._post(self._dataset_url("records"), {"records": records}, timeout=UPLOAD_TIMEOUT),
            ),
        )

    def process(self, overrides: Mapping[str, float | int] | None = None) -> BiographicSet:
        """Start (or retry) indexing and scoring; `overrides` apply to this run only."""
        return cast(
            "BiographicSet",
            self._request("process", lambda: self._post(self._dataset_url("process"), dict(overrides or {}))),
        )

    def approve(self) -> BiographicSet:
        return cast("BiographicSet", self._request("approve", lambda: self._post(self._dataset_url("approve"))))

    def reject(self) -> BiographicSet:
        return cast("BiographicSet", self._request("reject", lambda: self._post(self._dataset_url("reject"))))

    def cancel(self) -> BiographicSet:
        return cast("BiographicSet", self._request("cancel", lambda: self._post(self._dataset_url("cancel"))))

    def retrieve_findings(self) -> list[BiographicFinding]:
        """Retrieve every finding of the set, best score first."""
        url = self._dataset_url("findings")
        findings: list[BiographicFinding] = []
        expected: int | None = None
        page = 1

        while True:
            result = cast(
                "PaginatedBiographicFindings",
                self._request(
                    "retrieve_findings",
                    lambda page=page: self._get(url, params={"page": str(page), "page_size": str(FINDINGS_PAGE_SIZE)}),
                ),
            )
            expected = result["count"] if expected is None else expected
            findings.extend(result["results"])
            if result.get("next") is None:
                break
            page += 1

        if expected is None or len(findings) != expected:
            raise RemoteError(f"Biographic DedupEngine: findings count={expected!r}, received={len(findings)}")
        return findings
