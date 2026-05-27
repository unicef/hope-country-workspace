from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from requests import Session
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    RequestException,
    Timeout as RequestsTimeout,
)

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from . import endpoint, request, resource, response


@dataclass(slots=True)
class Client:
    group_reference_id: str
    session: Session
    api_root: endpoint.APIRoot
    deduplication_set_id: str | None = None

    @property
    def deduplication_set_group_endpoint(self) -> endpoint.DeduplicationSetGroup:
        return self.api_root.deduplication_set_groups.deduplication_set_group(self.group_reference_id)

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
    ) -> RemoteError | RemoteUnavailableError:
        req = getattr(response_obj, "request", None) if response_obj is not None else None
        target = f"{getattr(req, 'method', '')} {getattr(req, 'url', '')}".strip() or operation

        details = ""
        if response_obj is not None:
            details = (
                f". Status: {getattr(response_obj, 'status_code', None)}"
                f". Response: {getattr(response_obj, 'text', None)}"
            )

        return error_cls(f"DedupEngine: {target} failed: {err}{details}")

    def _request[T](self, operation: str, fn: Callable[[], T]) -> T:
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
        payload: request.CreateDeduplicationSet = {"reference_pk": self.group_reference_id}
        if self.deduplication_set_id:
            payload["id"] = self.deduplication_set_id

        result = self._request(
            "create_deduplication_set",
            lambda: collection.create(payload),
        )
        created = cast("response.CreatedDeduplicationSet", result)
        self.deduplication_set_id = created.get("id") or self.deduplication_set_id
        return created

    def can_create_deduplication_set(self) -> bool:
        def fetch() -> bool:
            result = self.session.get(str(self.deduplication_set_group_endpoint.status), timeout=resource.TIMEOUT)
            result.raise_for_status()
            value = result.json()["can_create"]
            if not isinstance(value, bool):
                raise RemoteError("DedupEngine: status response has invalid can_create value")
            return value

        return self._request("can_create_deduplication_set", fetch)

    def create_images(
        self,
        images: list[request.CreateEncoding],
    ) -> list[response.CreatedEncoding]:
        collection = resource.ImagesCollection(
            self.session,
            self.deduplication_set_endpoint.images,
        )
        result = self._request("create_images", lambda: collection.create(images))
        return cast("list[response.CreatedEncoding]", result)

    def ready(self) -> None:
        action = resource.ReadyDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.ready,
        )
        self._request("ready", action.call)

    def process(self, *, encode_only: bool = False) -> None:
        action = resource.ProcessDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.process,
        )
        params = {"encode_only": "true"} if encode_only else None
        self._request("process", lambda: action.call(params=params))

    def reject(self) -> None:
        action = resource.RejectDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.reject,
        )
        self._request("reject", action.call)

    def approve(self) -> None:
        action = resource.ApproveDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.approve,
        )
        self._request("approve", action.call)

    def retrieve_deduplication_set(self) -> response.DeduplicationSet:
        item = resource.DeduplicationSetItem(self.session, self.deduplication_set_endpoint)
        result = self._request("retrieve_deduplication_set", item.retrieve)
        return cast("response.DeduplicationSet", result)

    def get_deduplication_set_group_config(self) -> response.DeduplicationSetGroupConfig:
        item = resource.DeduplicationSetGroupConfigItem(
            self.session,
            self.deduplication_set_group_endpoint.config,
        )
        result = self._request("get_deduplication_set_group_config", item.retrieve)
        return cast("response.DeduplicationSetGroupConfig", result)

    def post_deduplication_set_group_config(
        self,
        payload: request.DeduplicationSetGroupConfig,
    ) -> response.DeduplicationSetGroupConfig:
        item = resource.DeduplicationSetGroupConfigItem(
            self.session,
            self.deduplication_set_group_endpoint.config,
        )
        result = self._request(
            "post_deduplication_set_group_config",
            lambda: item.update(payload),
        )
        return cast("response.DeduplicationSetGroupConfig", result)
