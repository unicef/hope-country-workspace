from dataclasses import dataclass
from typing import Any

from constance import config
from requests import Session
from requests.adapters import HTTPAdapter

from country_workspace.contrib.dedup_engine import endpoint, resource, request, response
from country_workspace.utils.auth import Auth


@dataclass
class Client:
    program_id: str
    session: Session
    api_root: endpoint.APIRoot

    def deduplicate(self, images: list[request.Image], settings: dict[str, Any]) -> None:
        deduplication_set_collection = resource.DeduplicationSetCollection(
            self.session, self.api_root.deduplication_sets
        )
        deduplication_set_collection.create({"reference_pk": self.program_id, "settings": settings})

        deduplication_set_endpoint = self.api_root.deduplication_sets.deduplication_set(self.program_id)
        image_collection = resource.ImagesBulkCollection(self.session, deduplication_set_endpoint.images_bulk)
        image_collection.create(images)

        process_action = resource.ProcessDeduplicationSetAction(self.session, deduplication_set_endpoint.process)
        process_action.call()

    def status(self) -> response.Status:
        deduplication_set_endpoint = self.api_root.deduplication_sets.deduplication_set(self.program_id)
        deduplication_set_item = resource.DeduplicationSetItem(self.session, deduplication_set_endpoint)
        deduplication_set = deduplication_set_item.retrieve()

        try:
            return response.Status(deduplication_set["status"].lower())
        except ValueError:
            return response.Status.UNKNOWN


def make_client(program_id: str) -> Client:
    session = Session()
    session.mount("https://", HTTPAdapter(max_retries=3))
    session.auth = Auth(config.DEDUP_API_TOKEN)
    api_root = endpoint.APIRoot(config.DEDUP_API_URL)

    return Client(program_id, session, api_root)
