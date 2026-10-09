from collections.abc import Iterable, Iterator
from itertools import batched
from uuid import UUID

from django.contrib.contenttypes.models import ContentType

from country_workspace.exceptions import MissingFlexFileError
from country_workspace.models import Rdp
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.contrib.dedup_engine.client import Client
from country_workspace.rdp.repository import qs_individuals_for_rdp
from country_workspace.utils.flex_files import as_data_uri
from country_workspace.workspaces.models import CountryIndividual

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
        individual_content_type: ContentType | None = None
        rows = (
            qs_individuals_for_rdp(rdp=self.rdp)
            .values_list("id", "flex_fields__photo")
            .iterator(chunk_size=IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE)
        )
        for batch in batched(rows, IMAGES_TO_DEDUPLICATE_BULK_BATCH_SIZE):
            plain, references = self._split_photo_values(batch)
            yield from plain
            if not references:
                continue
            # Looked up lazily: batches with no file references (for example, legacy
            # plain filenames) never need it, and stay free of DB access.
            if individual_content_type is None:
                individual_content_type = ContentType.objects.get_for_model(CountryIndividual, for_concrete_model=True)
            yield from self._resolve_references(references, individual_content_type)

    @staticmethod
    def _split_photo_values(
        batch: Iterable[tuple[int, object]],
    ) -> tuple[list[dict[str, str]], dict[UUID, list[int]]]:
        """Split a batch of `(pk, photo)` rows into plain values and grouped references."""
        plain: list[dict[str, str]] = []
        references: dict[UUID, list[int]] = {}
        for pk, photo in batch:
            if not isinstance(photo, str) or not (photo := photo.strip()):
                continue
            if (file_id := FlexFieldFile.parse_reference(photo)) is None:
                plain.append({"reference_pk": str(pk), "filename": photo})
            else:
                references.setdefault(file_id, []).append(pk)
        return plain, references

    @staticmethod
    def _resolve_references(references: dict[UUID, list[int]], content_type: ContentType) -> Iterator[dict[str, str]]:
        """Resolve references to data-URIs, owned by the individual that stored each one.

        Matching by pk alone would let one individual's photo be sent under another's
        `reference_pk` if a foreign reference ever leaked in, so ownership is checked too.
        """
        expected_pks = {pk for pks in references.values() for pk in pks}
        resolved: set[int] = set()
        flex_files = FlexFieldFile.objects.with_content().filter(
            content_type=content_type,
            object_id__in=expected_pks,
            pk__in=list(references),
        )
        for flex_file in flex_files:
            owner_pks = [pk for pk in references[flex_file.pk] if pk == flex_file.object_id]
            if not owner_pks:
                continue
            data_uri = as_data_uri(flex_file)
            for pk in owner_pks:
                resolved.add(pk)
                yield {"reference_pk": str(pk), "filename": data_uri}

        if missing := expected_pks - resolved:
            raise MissingFlexFileError(f"Individuals {sorted(missing)}: field 'photo' references missing files")

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
