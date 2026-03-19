from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NamedTuple, TypeVar

from constance import config
from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import HTTPError, RequestException
from rest_framework.status import HTTP_404_NOT_FOUND

from country_workspace.contrib.dedup_engine import endpoint, resource, request, response
from country_workspace.exceptions import RemoteError
from country_workspace.utils.auth import Auth


T = TypeVar("T")


class Status(NamedTuple):
    status: response.Status
    duplicates_found: int


@dataclass(slots=True)
class Client:
    program_id: str
    session: Session
    api_root: endpoint.APIRoot

    @property
    def deduplication_set_endpoint(self) -> endpoint.DeduplicationSet:
        return self.api_root.deduplication_sets.deduplication_set(self.program_id)

    def _err(self, operation: str, err: Exception, response_obj: Any | None = None) -> RemoteError:
        req = getattr(response_obj, "request", None) if response_obj is not None else None
        target = f"{getattr(req, 'method', '')} {getattr(req, 'url', '')}".strip() or operation

        details = ""
        if response_obj is not None:
            details = (
                f". Status: {getattr(response_obj, 'status_code', None)}"
                f". Response: {getattr(response_obj, 'text', None)}"
            )

        return RemoteError(f"DedupEngine: {target} failed: {err}{details}")

    def _request(self, operation: str, fn: Callable[[], T]) -> T:
        try:
            return fn()
        except (RequestException, ValueError, KeyError, TypeError) as exc:
            raise self._err(operation, exc, getattr(exc, "response", None)) from exc

    def create_deduplication_set(self) -> str:
        deduplication_set_collection = resource.DeduplicationSetCollection(
            self.session,
            self.api_root.deduplication_sets,
        )
        return self._request(
            "create_deduplication_set",
            lambda: deduplication_set_collection.create({"reference_pk": self.program_id})["id"],
        )

    def create_images(self, images: list[request.Image]) -> None:
        image_collection = resource.ImagesBulkCollection(
            self.session,
            self.deduplication_set_endpoint.images_bulk,
        )
        self._request("create_images", lambda: image_collection.create(images))

    def process(self) -> None:
        process_action = resource.ProcessDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.process,
        )
        self._request("process", lambda: process_action.call(None))

    def approve(self) -> None:
        reject_action = resource.RejectDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.reject,
        )
        payload: request.Reject = {
            "action": "reject",
            "reference_pks": [],
        }
        self._request("approve", lambda: reject_action.call(payload))

    def status(self) -> Status:
        deduplication_set_item = resource.DeduplicationSetItem(
            self.session,
            self.deduplication_set_endpoint,
        )
        try:
            deduplication_set = deduplication_set_item.retrieve()
        except HTTPError as exc:
            response_obj = exc.response
            if response_obj is not None and response_obj.status_code == HTTP_404_NOT_FOUND:
                return Status(response.Status.NOT_SCHEDULED, -1)
            raise self._err("status", exc, response_obj) from exc
        except (RequestException, ValueError, KeyError, TypeError) as exc:
            raise self._err("status", exc, getattr(exc, "response", None)) from exc

        if not isinstance(deduplication_set, dict):
            raise self._err("status", TypeError("malformed JSON response"))

        raw_status = deduplication_set.get("status")
        try:
            status = response.Status(raw_status.lower()) if isinstance(raw_status, str) else response.Status.UNKNOWN
        except ValueError:
            status = response.Status.UNKNOWN

        duplicates_found = deduplication_set.get("duplicates_found")
        if not isinstance(duplicates_found, int):
            duplicates_found = -1

        return Status(status, duplicates_found)

    def get_deduplication_set_group_config(self) -> response.DeduplicationSetGroupConfig:
        item = resource.DeduplicationSetGroupConfigItem(
            self.session,
            self.api_root.deduplication_set_groups.config(self.program_id),
        )
        payload = self._request("get_deduplication_set_group_config", item.retrieve)
        if not isinstance(payload, dict):
            raise self._err("get_deduplication_set_group_config", TypeError("malformed JSON response"))
        return payload

    def post_deduplication_set_group_config(
        self,
        payload: request.DeduplicationSetGroupConfig,
    ) -> None:
        action = resource.DeduplicationSetGroupConfigAction(
            self.session,
            self.api_root.deduplication_set_groups.config(self.program_id),
        )
        self._request("post_deduplication_set_group_config", lambda: action.call(payload))


@contextmanager
def make_client(program_id: str) -> Generator[Client, None, None]:
    with Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=3))
        session.auth = Auth(config.DEDUP_API_TOKEN)
        api_root = endpoint.APIRoot(config.DEDUP_API_URL)

        yield Client(program_id, session, api_root)
