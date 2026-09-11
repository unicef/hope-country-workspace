from itertools import batched
from collections.abc import Iterator
from uuid import UUID

from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models import Rdp
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.contrib.dedup_engine.client import Client
from country_workspace.rdp.repository import qs_individuals_for_rdp
from country_workspace.utils.flex_files import as_data_uri

from .constants import IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE


class BiometricDedupProcessor:
    """Build and upload biometric deduplication input for an RDP."""

    def __init__(self, rdp: Rdp) -> None:
        self.rdp = rdp

    def _iter_images(self) -> Iterator[dict[str, str]]:
        """Yield DedupEngine images payload from RDP individuals.

        Photos are read one batch of references at a time, so the engine still
        receives data-URIs without ever loading a whole beneficiary row.
        """
        rows = (
            qs_individuals_for_rdp(rdp=self.rdp)
            .values_list("id", "flex_fields__photo")
            .iterator(chunk_size=IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE)
        )
        for batch in batched(rows, IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE):
            references: dict[UUID, list[int]] = {}
            for pk, photo in batch:
                if not isinstance(photo, str) or not (photo := photo.strip()):
                    continue
                if (file_id := FlexFieldFile.parse_reference(photo)) is None:
                    yield {"reference_pk": str(pk), "filename": photo}
                else:
                    references.setdefault(file_id, []).append(pk)

            found: set[UUID] = set()
            for flex_file in FlexFieldFile.objects.with_content().filter(pk__in=list(references)):
                found.add(flex_file.pk)
                data_uri = as_data_uri(flex_file)
                for pk in references[flex_file.pk]:
                    yield {"reference_pk": str(pk), "filename": data_uri}
            if missing := set(references) - found:
                pks = sorted({pk for file_id in missing for pk in references[file_id]})
                raise MissingFlexFileError(f"Individuals {pks}: field 'photo' references missing files")

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
