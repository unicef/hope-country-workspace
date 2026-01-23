from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NamedTuple
from uuid import UUID

from constance import config
from requests import Session
from requests.adapters import HTTPAdapter

from country_workspace.contrib.dedup_engine import endpoint, resource, request, response
from country_workspace.utils.auth import Auth


class Status(NamedTuple):
    status: response.Status
    duplicates_found: int
    deduplication_set_id: UUID | None = None


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
        deduplication_set_endpoint = self.api_root.deduplication_sets.deduplication_set(self.program_id)
        deduplication_set_item = resource.DeduplicationSetItem(self.session, deduplication_set_endpoint)
        deduplication_set = deduplication_set_item.retrieve()

        try:
            status = response.Status(deduplication_set["status"].lower())
        except (ValueError, KeyError):
            status = response.Status.UNKNOWN

        try:
            duplicates_found = deduplication_set["duplicates_found"]
        except KeyError:
            duplicates_found = -1

        try:
            deduplication_set_id = UUID(deduplication_set["id"])
        except (TypeError, ValueError, KeyError):
            deduplication_set_id = None

        return Status(status, duplicates_found, deduplication_set_id)


@contextmanager
def make_client(program_id: str) -> Generator[Client, None, None]:
    with Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=3))
        session.auth = Auth(config.DEDUP_API_TOKEN)
        api_root = endpoint.APIRoot(config.DEDUP_API_URL)

        yield Client(program_id, session, api_root)
