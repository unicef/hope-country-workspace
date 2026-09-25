from typing import TYPE_CHECKING
from itertools import batched

from country_workspace.rdp.repository import qs_individuals_for_rdp

from .constants import IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE

if TYPE_CHECKING:
    from collections.abc import Iterator
    from country_workspace.models import Rdp
    from country_workspace.contrib.dedup_engine.client import Client
    from country_workspace.contrib.dedup_engine.request import CreateEncoding


class BiometricDedupProcessor:
    """Build and upload biometric deduplication input for an RDP."""

    def __init__(self, rdp: Rdp) -> None:
        self.rdp = rdp

    def _iter_images(self) -> Iterator[CreateEncoding]:
        """Yield DedupEngine image payloads for RDP individuals."""
        qs = qs_individuals_for_rdp(rdp=self.rdp).values_list("id", "flex_fields__photo")
        for pk, photo in qs.iterator(chunk_size=IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE):
            if isinstance(photo, str) and (photo := photo.strip()):
                yield {"reference_pk": str(pk), "filename": photo}

    def upload_images(self, client: Client) -> int:
        """Upload biometric images and return the number submitted."""
        images_sent = 0
        for batch in batched(self._iter_images(), IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE, strict=False):
            payload = list(batch)
            client.create_images(payload)
            images_sent += len(payload)
        return images_sent
