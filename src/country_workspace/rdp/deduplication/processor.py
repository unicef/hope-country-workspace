from collections.abc import Iterator
from typing import Any
from itertools import batched
from uuid import UUID

from country_workspace.contrib.dedup_engine import make_dedup_client
from country_workspace.models import Rdp
from country_workspace.rdp.processor import ProcessorBase
from country_workspace.rdp.repository import qs_individuals_for_rdp

from .constants import IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE


class DedupProcessor(ProcessorBase):
    """Dedup pipeline: create/upload/process or process an existing DE set."""

    PREFIX = "Dedup"

    def __init__(self, rdp: Rdp) -> None:
        super().__init__()
        self.rdp = rdp
        self.group_reference_id = rdp.program.unicef_id

    def run(self, notification_url: str | None = None) -> None:
        ds_id = self.rdp.deduplication_set_id
        self.total |= {
            "rdp_id": self.rdp.pk,
            "program": self.group_reference_id,
            "images_sent": 0,
            "deduplication_set_id": str(ds_id) if ds_id else None,
        }

        if ds_id is None:
            self.fail("deduplication_set_id", "is not set")
            return

        with make_dedup_client(self.group_reference_id, deduplication_set_id=str(ds_id)) as client:
            can_create = self.try_remote("can_create_deduplication_set", client.can_create_deduplication_set)
            if can_create is None:
                return
            if can_create:
                self.total["images_sent"] = self.deduplicate(client, ds_id, notification_url=notification_url)
                return
            self.run_remote("process_existing_deduplication_set", client.process)

    def _iter_images(self) -> Iterator[dict[str, str]]:
        """Yield DedupEngine images payload from RDP individuals."""
        for pk, photo in (
            qs_individuals_for_rdp(rdp=self.rdp)
            .values_list("id", "flex_fields__photo")
            .iterator(chunk_size=IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE)
        ):
            if isinstance(photo, str) and (photo := photo.strip()):
                yield {"reference_pk": str(pk), "filename": photo}

    def create_deduplication_set(
        self, client: Any, deduplication_set_id: UUID, notification_url: str | None = None
    ) -> bool:
        """Create a remote deduplication set using the CW-owned UUID."""
        payload = self.try_remote(
            "create_deduplication_set",
            lambda: client.create_deduplication_set(notification_url=notification_url),
        )
        if payload is None:
            return False

        expected_id = str(deduplication_set_id)
        if payload.get("id") != expected_id:
            self.fail(
                "create_deduplication_set",
                f"response id mismatch expected={expected_id} got={payload.get('id')!r}",
                response=payload,
            )
            return False

        return True

    def upload_images(self, client: Any) -> tuple[bool, int]:
        images_sent = 0

        for batch in batched(self._iter_images(), IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE):
            payload = list(batch)
            if not self.run_remote("create_images", lambda payload=payload: client.create_images(payload)):
                return False, images_sent
            images_sent += len(payload)

        if not images_sent:
            self.fail("create_images", "no images to deduplicate")
            return False, images_sent

        if not self.run_remote("ready", client.ready):
            return False, images_sent

        return True, images_sent

    def deduplicate(self, client: Any, deduplication_set_id: UUID, notification_url: str | None = None) -> int:
        """Create, upload, and process a DedupEngine set; return sent images count."""
        if not self.create_deduplication_set(client, deduplication_set_id, notification_url=notification_url):
            return 0

        uploaded, images_sent = self.upload_images(client)
        if not uploaded:
            return images_sent

        if not self.run_remote("process", client.process):
            return images_sent

        return images_sent
