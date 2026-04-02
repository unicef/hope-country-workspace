from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from requests import Session
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    RequestException,
    Timeout as RequestsTimeout,
)

from country_workspace.contrib.dedup_engine import endpoint, request, resource, response
from country_workspace.contrib.dedup_engine.validation import (
    expect_mapping,
    get_optional_str,
    get_required_bool,
)
from country_workspace.exceptions import RemoteError, RemoteUnavailableError


T = TypeVar("T")


@dataclass(slots=True)
class Client:
    program_id: str
    session: Session
    api_root: endpoint.APIRoot
    deduplication_set_id: str | None = None

    @property
    def deduplication_set_endpoint(self) -> endpoint.DeduplicationSet:
        return self.api_root.deduplication_sets.deduplication_set(self._require_deduplication_set_id())

    def _require_deduplication_set_id(self) -> str:
        if self.deduplication_set_id:
            return self.deduplication_set_id
        raise RemoteError("DedupEngine: deduplication_set_id is not set")

    def _err(
        self,
        operation: str,
        err: Exception,
        response_obj: Any | None = None,
        *,
        error_cls: type[RemoteError] | type[RemoteUnavailableError] = RemoteError,
    ) -> Exception:
        req = getattr(response_obj, "request", None) if response_obj is not None else None
        target = f"{getattr(req, 'method', '')} {getattr(req, 'url', '')}".strip() or operation

        details = ""
        if response_obj is not None:
            details = (
                f". Status: {getattr(response_obj, 'status_code', None)}"
                f". Response: {getattr(response_obj, 'text', None)}"
            )

        return error_cls(f"DedupEngine: {target} failed: {err}{details}")

    def _request(self, operation: str, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except (RequestsConnectionError, RequestsTimeout) as exc:
            raise self._err(operation, exc, getattr(exc, "response", None), error_cls=RemoteUnavailableError) from exc
        except HTTPError as exc:
            response_obj = exc.response
            status_code = getattr(response_obj, "status_code", None)
            error_cls = RemoteUnavailableError if isinstance(status_code, int) and status_code >= 500 else RemoteError
            raise self._err(operation, exc, response_obj, error_cls=error_cls) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise self._err(operation, exc, getattr(exc, "response", None)) from exc
        except RequestException as exc:
            raise self._err(operation, exc, getattr(exc, "response", None), error_cls=RemoteUnavailableError) from exc

    def create_deduplication_set(self) -> response.CreatedDeduplicationSet:
        collection = resource.DeduplicationSetCollection(
            self.session,
            self.api_root.deduplication_sets,
        )
        result = self._request(
            "create_deduplication_set",
            lambda: collection.create({"reference_pk": self.program_id}),
        )
        self.deduplication_set_id = get_optional_str(result, "id")
        return result

    def can_create_deduplication_set(self) -> bool:
        def fetch() -> bool:
            result = self.session.get(str(self.api_root.deduplication_set_groups.status(self.program_id)))
            result.raise_for_status()
            payload = expect_mapping(result.json(), "can_create_deduplication_set")
            return get_required_bool(payload, "can_create", "can_create_deduplication_set")

        return self._request("can_create_deduplication_set", fetch)

    def create_images(
        self,
        images: list[request.CreateEncoding],
        *,
        last: bool = False,
    ) -> list[response.CreatedEncoding]:
        collection = resource.ImagesCollection(
            self.session,
            self.deduplication_set_endpoint.images,
        )
        params = {"last": "true"} if last else None
        return self._request("create_images", lambda: collection.create(images, params=params))

    def process(self) -> None:
        action = resource.ProcessDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.process,
        )
        self._request("process", action.call)

    def reject(self) -> None:
        action = resource.RejectDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.reject,
        )
        self._request("reject", action.call)

    def retrieve_deduplication_set(self) -> response.DeduplicationSet:
        item = resource.DeduplicationSetItem(self.session, self.deduplication_set_endpoint)
        return self._request("retrieve_deduplication_set", item.retrieve)

    def get_deduplication_set_group_config(self) -> response.DeduplicationSetGroupConfig:
        item = resource.DeduplicationSetGroupConfigItem(
            self.session,
            self.api_root.deduplication_set_groups.config(self.program_id),
        )
        return self._request("get_deduplication_set_group_config", item.retrieve)

    def post_deduplication_set_group_config(
        self,
        payload: request.DeduplicationSetGroupConfig,
    ) -> response.DeduplicationSetGroupConfig:
        item = resource.DeduplicationSetGroupConfigItem(
            self.session,
            self.api_root.deduplication_set_groups.config(self.program_id),
        )
        return self._request(
            "post_deduplication_set_group_config",
            lambda: item.update(payload),
        )
