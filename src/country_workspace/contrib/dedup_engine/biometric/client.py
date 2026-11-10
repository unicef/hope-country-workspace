from dataclasses import dataclass
from functools import partial
from http import HTTPStatus

from requests import Session
from requests.exceptions import HTTPError

from country_workspace.exceptions import RemoteError

from ..client import BaseClient
from ..resource import TIMEOUT
from . import endpoint, request, resource, response
from .exceptions import DeduplicationSetGroupBusyError


@dataclass(slots=True)
class Client(BaseClient):
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

    def can_create_deduplication_set(self) -> bool:
        def fetch() -> bool:
            result = self.session.get(str(self.deduplication_set_group_endpoint.status), timeout=TIMEOUT)
            result.raise_for_status()
            value = result.json()["can_create"]
            if not isinstance(value, bool):
                raise RemoteError("DedupEngine: status response has invalid can_create value")
            return value

        return self._request("can_create_deduplication_set", fetch)

    def get_deduplication_set_group_config(
        self,
        *,
        timeout: tuple[int, int] = TIMEOUT,
    ) -> response.DeduplicationSetGroupConfig:
        item = resource.DeduplicationSetGroupConfigItem(self.session, self.deduplication_set_group_endpoint.config)
        return self._request("get_deduplication_set_group_config", partial(item.retrieve, timeout=timeout))

    def post_deduplication_set_group_config(
        self,
        payload: request.DeduplicationSetGroupConfig,
    ) -> response.DeduplicationSetGroupConfig:
        item = resource.DeduplicationSetGroupConfigItem(self.session, self.deduplication_set_group_endpoint.config)
        return self._request("post_deduplication_set_group_config", lambda: item.update(payload))

    def delete_deduplication_set_group(self) -> None:
        """Delete the deduplication set group."""
        item = resource.DeduplicationSetGroupItem(self.session, self.deduplication_set_group_endpoint)

        def delete() -> None:
            try:
                item.delete()
            except HTTPError as exc:
                status_code = getattr(exc.response, "status_code", None)
                if status_code == HTTPStatus.NOT_FOUND:
                    return
                if status_code == HTTPStatus.CONFLICT:
                    raise self._err(
                        "delete_deduplication_set_group",
                        exc,
                        exc.response,
                        error_cls=DeduplicationSetGroupBusyError,
                    ) from exc
                raise

        self._request("delete_deduplication_set_group", delete)

    def create_deduplication_set(self, notification_url: str | None = None) -> response.CreatedDeduplicationSet:
        collection = resource.DeduplicationSetCollection(self.session, self.api_root.deduplication_sets)
        payload: request.CreateDeduplicationSet = {"reference_pk": self.group_reference_id}
        if self.deduplication_set_id:
            payload["id"] = self.deduplication_set_id
        if notification_url:
            payload["notification_url"] = notification_url
            payload["notify"] = True

        created = self._request("create_deduplication_set", lambda: collection.create(payload))
        self.deduplication_set_id = created.get("id") or self.deduplication_set_id
        return created

    def retrieve_deduplication_set(self) -> response.DeduplicationSet:
        item = resource.DeduplicationSetItem(self.session, self.deduplication_set_endpoint)
        return self._request("retrieve_deduplication_set", item.retrieve)

    def retrieve_deduplication_set_or_none(self) -> response.DeduplicationSet | None:
        """Retrieve the deduplication set if it exists."""
        item = resource.DeduplicationSetItem(self.session, self.deduplication_set_endpoint)
        return self._request("retrieve_deduplication_set", item.retrieve_or_none)

    def create_images(self, images: list[request.CreateEncoding]) -> list[response.CreatedEncoding]:
        collection = resource.ImagesCollection(self.session, self.deduplication_set_endpoint.images)
        return self._request("create_images", lambda: collection.create(images))

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

    def retrieve_findings(self) -> list[response.Finding]:
        """Retrieve all findings."""
        collection = resource.FindingsCollection(self.session, self.deduplication_set_endpoint.findings)
        findings: list[response.Finding] = []
        page = 1

        while True:
            result = self._request(
                "retrieve_findings",
                partial(collection.list, params={"page": str(page)}),
            )
            findings.extend(result["results"])
            if result.get("next") is None:
                return findings
            page += 1

    def approve(self) -> None:
        action = resource.ApproveDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.approve,
        )
        self._request("approve", action.call)

    def reject(self) -> None:
        action = resource.RejectDeduplicationSetAction(
            self.session,
            self.deduplication_set_endpoint.reject,
        )
        self._request("reject", action.call)
