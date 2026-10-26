import base64
import binascii
import hashlib
from collections.abc import Collection
from typing import TYPE_CHECKING, Any

from azure.core.exceptions import AzureError
from django.core.files.base import ContentFile

from country_workspace.exceptions import BlobStorageError, MissingFlexFileError
from country_workspace.models.flex_file import FlexFieldFile
from country_workspace.storages import HOPE_STORAGE
from country_workspace.utils.flex_files import load_flex_files

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from country_workspace.models.base import Validable
    from country_workspace.models.mixins import HopeBlobMixin

PREFIX = "data:"
# hope_blob_key() reads record.country_office and record.program; join them once per query.
RECORD_SELECT_RELATED = "batch__program__country_office"


def is_data_uri(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX) and ";base64," in value


def decode_data_uri(value: str) -> bytes:
    return base64.b64decode(value.partition(";base64,")[2], validate=True)


def image_field_names(checker: "DataChecker") -> set[str]:
    return checker.get_file_field_names()


def sync_record_blobs(
    record: "Validable | HopeBlobMixin",
    image_fields: Collection[str],
    only: set[str] | None = None,
) -> dict[str, str]:
    """Reconcile record images with the shared HOPE blob storage.

    Handles both an offloaded `FlexFieldFile` reference and a legacy inline
    data-URI, and returns the blob key for every image field that has a value.

    Raises BlobStorageError when the storage backend is unreachable or fails,
    or when a flex-field contains a malformed base64 payload. Raises
    MissingFlexFileError when a flex-field references a file row the record
    does not own.
    """
    try:
        return _sync_record_blobs(record, image_fields, only)
    except (AzureError, OSError, binascii.Error) as e:
        raise BlobStorageError(
            f"blob sync failed for {type(record).__name__} #{record.pk}: {e.__class__.__name__}: {e}"
        ) from e


def _sync_record_blobs(
    record: "Validable | HopeBlobMixin",
    image_fields: Collection[str],
    only: set[str] | None,
) -> dict[str, str]:
    hashes = dict(record.blob_hashes or {})
    result: dict[str, str] = {}
    present: set[str] = set()
    names = [name for name in image_fields if only is None or name in only]

    # Reference fields are loaded together up front, so a record with several
    # offloaded image fields costs one query instead of one per field.
    reference_ids = {
        name: file_id
        for name in names
        if (file_id := FlexFieldFile.parse_reference(record.flex_fields.get(name))) is not None
    }
    files = load_flex_files(record, set(reference_ids.values())) if reference_ids else {}

    for name in names:
        value = record.flex_fields.get(name)
        if name in reference_ids:
            if (flex_file := files.get(reference_ids[name])) is None:
                raise MissingFlexFileError(
                    f"{type(record).__name__} #{record.pk}: field {name!r} references missing file {value}"
                )
            new_hash = flex_file.checksum
            content = flex_file.content_bytes
        elif is_data_uri(value):
            content = decode_data_uri(value)
            new_hash = hashlib.sha256(content).hexdigest()
        else:
            continue

        present.add(name)
        key = record.hope_blob_key(name)
        if hashes.get(name) != new_hash:
            # HOPE_STORAGE must be configured with overwrite semantics (enforced by
            # checks.py E004), so save() replaces any existing blob under the same key.
            HOPE_STORAGE.save(key, ContentFile(content))
            hashes[name] = new_hash
        result[name] = key

    for name in list(hashes):
        if name not in present and (only is None or name in only):
            HOPE_STORAGE.delete(record.hope_blob_key(name))
            del hashes[name]

    if hashes != (record.blob_hashes or {}):
        record.blob_hashes = hashes
        type(record).objects.filter(pk=record.pk).update(blob_hashes=hashes)
    return result
