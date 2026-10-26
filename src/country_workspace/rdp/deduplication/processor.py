from itertools import batched
from collections.abc import Iterator

from country_workspace.models import Rdp
from country_workspace.contrib.dedup_engine.client import Client
from country_workspace.contrib.dedup_engine.request import CreateEncoding
from country_workspace.rdp.repository import qs_individuals_for_rdp
from country_workspace.services.hope_blob import RECORD_SELECT_RELATED, image_field_names, sync_record_blobs

from .constants import IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE


class BiometricDedupProcessor:
    """Build and upload biometric deduplication input for an RDP."""

    def __init__(self, rdp: Rdp) -> None:
        self.rdp = rdp

    def _iter_images(self) -> Iterator[CreateEncoding]:
        """Yield DedupEngine image payloads for RDP individuals."""
        qs = qs_individuals_for_rdp(rdp=self.rdp).select_related(RECORD_SELECT_RELATED)
        image_fields = image_field_names(self.rdp.program.individual_checker)
        for ind in qs.iterator(chunk_size=IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE):
            paths = sync_record_blobs(ind, image_fields, only={"photo"})
            if photo := paths.get("photo"):
                yield {"reference_pk": str(ind.pk), "filename": photo}

    def has_images(self) -> bool:
        """Return whether the RDP has at least one biometric image."""
        return next(self._iter_images(), None) is not None

    def upload_images(self, client: Client) -> int:
        """Upload biometric images and return the number submitted."""
        images_sent = 0
        for batch in batched(self._iter_images(), IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE, strict=False):
            payload = list(batch)
            client.create_images(payload)
            images_sent += len(payload)
        return images_sent
