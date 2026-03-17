from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NamedTuple

from constance import config
from requests import Session
from requests.adapters import HTTPAdapter

from country_workspace.contrib.dedup_engine import endpoint, resource, request, response
from country_workspace.utils.auth import Auth


_STUB_DEDUPLICATION_SET_GROUP_CONFIG: response.DeduplicationSetGroupConfig = {
    "threshold_1": 0.1,
    "threshold_2": 0.2,
    "threshold_3": 0.3,
}


class Status(NamedTuple):
    status: response.Status
    duplicates_found: int


@dataclass
class Client:
    program_id: str
    session: Session
    api_root: endpoint.APIRoot

    @property
    def deduplication_set_endpoint(self) -> endpoint.DeduplicationSet:
        return self.api_root.deduplication_sets.deduplication_set(self.program_id)

    def create_deduplication_set(self, settings: dict[str, Any]) -> str:
        deduplication_set_collection = resource.DeduplicationSetCollection(
            self.session, self.api_root.deduplication_sets
        )
        deduplication_set = deduplication_set_collection.create({"reference_pk": self.program_id, "settings": settings})
        return deduplication_set["id"]

    def create_images(self, images: list[request.Image]) -> None:
        image_collection = resource.ImagesBulkCollection(self.session, self.deduplication_set_endpoint.images_bulk)
        image_collection.create(images)

    def process(self) -> None:
        process_action = resource.ProcessDeduplicationSetAction(self.session, self.deduplication_set_endpoint.process)
        process_action.call(None)

    def approve(self) -> None:
        # we use reject action here and pass an empty pks list
        reject_action = resource.RejectDeduplicationSetAction(self.session, self.deduplication_set_endpoint.reject)
        reject_action.call(
            {
                "action": "reject",
                "reference_pks": [],
            }
        )

    def deduplicate(self, images: list[request.Image], settings: dict[str, Any]) -> None:
        self.create_deduplication_set(settings)
        self.create_images(images)
        self.process()

    def status(self) -> Status:
        deduplication_set_item = resource.DeduplicationSetItem(self.session, self.deduplication_set_endpoint)
        deduplication_set = deduplication_set_item.retrieve()

        try:
            status = response.Status(deduplication_set["status"].lower())
        except (ValueError, KeyError):
            status = response.Status.UNKNOWN

        try:
            duplicates_found = deduplication_set["duplicates_found"]
        except KeyError:
            duplicates_found = -1

        return Status(status, duplicates_found)

    def get_deduplication_set_group_config(self) -> response.DeduplicationSetGroupConfig:
        return _STUB_DEDUPLICATION_SET_GROUP_CONFIG.copy()

    def post_deduplication_set_group_config(self, payload: request.DeduplicationSetGroupConfig) -> None:
        raise NotImplementedError(
            "DedupEngine endpoint is not implemented yet: "
            f"POST {self.api_root.deduplication_set_groups.config(self.program_id)}. "
            f"Payload: {payload!r}"
        )


@contextmanager
def make_client(program_id: str) -> Generator[Client, None, None]:
    with Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=3))
        session.auth = Auth(config.DEDUP_API_TOKEN)
        api_root = endpoint.APIRoot(config.DEDUP_API_URL)

        yield Client(program_id, session, api_root)
